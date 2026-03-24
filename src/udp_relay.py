from __future__ import annotations

import logging
import selectors
import socket
import time
from dataclasses import dataclass
from typing import Optional

from nanoscan_parser import NanoScanUdpInterpreter
from models import AppConfig, ScannerConfig
from stats import StatsRegistry
from telemetry_store import TelemetryStore
from utils import format_bytes_per_second, format_duration


@dataclass(frozen=True)
class ScannerRuntime:
    config: ScannerConfig
    sender_socket: socket.socket
    interpreter: Optional[NanoScanUdpInterpreter]


@dataclass(frozen=True)
class PortRoute:
    local_port: int
    scanners: tuple[ScannerRuntime, ...]
    by_source_ip: dict[str, ScannerRuntime]
    default_scanner: Optional[ScannerRuntime]

    def resolve(self, source_ip: str, source_filter_enabled: bool) -> Optional[ScannerRuntime]:
        if not source_filter_enabled:
            return self.scanners[0] if self.scanners else None

        matched = self.by_source_ip.get(source_ip)
        if matched is not None:
            return matched
        return self.default_scanner

    def drop_targets_for_unmatched(
        self,
        source_ip: str,
        source_filter_enabled: bool,
    ) -> tuple[ScannerRuntime, ...]:
        if not self.scanners:
            return ()

        if not source_filter_enabled:
            return (self.scanners[0],)

        if len(self.scanners) == 1:
            return (self.scanners[0],)

        if source_ip in self.by_source_ip:
            return ()

        return self.scanners


class UdpRelay:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        telemetry_store: Optional[TelemetryStore] = None,
    ) -> None:
        self._config = config
        self._logger = logger
        self._telemetry_store = telemetry_store
        self._selector = selectors.DefaultSelector()
        self._running = False

        self._receive_sockets: list[socket.socket] = []
        self._sender_sockets: list[socket.socket] = []
        self._recv_buffers: dict[socket.socket, bytearray] = {}
        self._recv_views: dict[socket.socket, memoryview] = {}
        self._routes_by_socket: dict[socket.socket, PortRoute] = {}
        self._telemetry_packet_counters: dict[str, int] = {}

        enabled_names = [scanner.name for scanner in self._config.enabled_scanners]
        self._stats = StatsRegistry(enabled_names)
        self._build_runtime()

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        for sock in self._receive_sockets:
            try:
                self._selector.unregister(sock)
            except Exception:
                pass
            self._safe_close(sock)

        for sock in self._sender_sockets:
            self._safe_close(sock)

        self._receive_sockets.clear()
        self._sender_sockets.clear()
        self._recv_buffers.clear()
        self._recv_views.clear()
        self._routes_by_socket.clear()

    def run(self) -> None:
        self._running = True
        general = self._config.general
        stats_interval = general.stats_interval_sec
        next_stats_time = time.monotonic() + stats_interval

        self._logger.info(
            "Relay iniciado com %d scanner(s) habilitado(s).",
            len(self._config.enabled_scanners),
        )

        try:
            while self._running:
                now = time.monotonic()
                timeout = max(0.0, next_stats_time - now)
                events = self._selector.select(timeout)

                for key, _ in events:
                    recv_socket: socket.socket = key.fileobj
                    route: PortRoute = key.data
                    self._drain_socket(recv_socket, route)

                now = time.monotonic()
                if now >= next_stats_time:
                    self._emit_stats(now)
                    next_stats_time = now + stats_interval
        finally:
            self.close()
            self._logger.info("Relay encerrado.")

    def _build_runtime(self) -> None:
        general = self._config.general
        runtimes: list[ScannerRuntime] = []

        for scanner in self._config.enabled_scanners:
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sender.setblocking(False)
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, general.send_socket_buffer_bytes)
            self._sender_sockets.append(sender)
            interpreter = None
            if self._telemetry_store is not None and self._config.web.enabled:
                interpreter = NanoScanUdpInterpreter(
                    max_sample_points=self._config.web.max_sample_points
                )
            runtimes.append(
                ScannerRuntime(
                    config=scanner,
                    sender_socket=sender,
                    interpreter=interpreter,
                )
            )
            self._telemetry_packet_counters[scanner.name] = 0

        routes_by_port: dict[int, list[ScannerRuntime]] = {}
        for runtime in runtimes:
            routes_by_port.setdefault(runtime.config.local_port, []).append(runtime)

        recv_buffer_size = general.max_expected_packet_size + 1
        for local_port, scanners_on_port in routes_by_port.items():
            route = self._build_route(local_port, scanners_on_port)
            recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            recv_socket.setblocking(False)
            recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, general.recv_socket_buffer_bytes)

            try:
                recv_socket.bind(("0.0.0.0", local_port))
            except OSError as exc:
                self.close()
                raise RuntimeError(
                    f"Falha ao fazer bind na porta local {local_port}: {exc}"
                ) from exc

            self._receive_sockets.append(recv_socket)
            self._selector.register(recv_socket, selectors.EVENT_READ, data=route)
            buffer = bytearray(recv_buffer_size)
            self._recv_buffers[recv_socket] = buffer
            self._recv_views[recv_socket] = memoryview(buffer)
            self._routes_by_socket[recv_socket] = route

            self._logger.info(
                "Escutando UDP 0.0.0.0:%d para %d scanner(s).",
                local_port,
                len(scanners_on_port),
            )

    def _build_route(self, local_port: int, scanners_on_port: list[ScannerRuntime]) -> PortRoute:
        by_source_ip: dict[str, ScannerRuntime] = {}
        default_scanner: Optional[ScannerRuntime] = None

        for runtime in scanners_on_port:
            if runtime.config.source_ip:
                by_source_ip[runtime.config.source_ip] = runtime
            else:
                default_scanner = runtime

        return PortRoute(
            local_port=local_port,
            scanners=tuple(scanners_on_port),
            by_source_ip=by_source_ip,
            default_scanner=default_scanner,
        )

    def _drain_socket(self, recv_socket: socket.socket, route: PortRoute) -> None:
        general = self._config.general
        read_limit = general.max_packets_per_socket_event
        buffer = self._recv_buffers[recv_socket]
        view = self._recv_views[recv_socket]

        for _ in range(read_limit):
            try:
                packet_size, source_addr = recv_socket.recvfrom_into(buffer)
            except BlockingIOError:
                break
            except OSError as exc:
                self._logger.error(
                    "Erro de recepcao na porta %d: %s",
                    route.local_port,
                    exc,
                )
                for runtime in route.scanners:
                    self._stats.mark_error(runtime.config.name)
                break

            source_ip = source_addr[0]
            self._handle_packet(route, source_ip, view, packet_size)

    def _handle_packet(
        self,
        route: PortRoute,
        source_ip: str,
        buffer_view: memoryview,
        packet_size: int,
    ) -> None:
        general = self._config.general
        now = time.monotonic()

        runtime = route.resolve(source_ip, general.source_ip_filter_enabled)
        if runtime is None:
            for drop_target in route.drop_targets_for_unmatched(
                source_ip=source_ip,
                source_filter_enabled=general.source_ip_filter_enabled,
            ):
                self._stats.mark_dropped(drop_target.config.name)
            if general.debug:
                self._logger.debug(
                    "Pacote descartado na porta %d por filtro de origem. source_ip=%s",
                    route.local_port,
                    source_ip,
                )
            return

        scanner_name = runtime.config.name
        if packet_size > general.max_expected_packet_size:
            self._stats.mark_dropped(scanner_name)
            if general.debug:
                self._logger.debug(
                    "Pacote do scanner '%s' excedeu max_expected_packet_size. bytes=%d limite=%d",
                    scanner_name,
                    packet_size,
                    general.max_expected_packet_size,
                )
            return

        self._stats.mark_received(scanner_name, packet_size, now)
        payload = buffer_view[:packet_size]
        for target in runtime.config.destinations:
            try:
                sent = runtime.sender_socket.sendto(payload, target.address)
            except (BlockingIOError, OSError) as exc:
                self._stats.mark_dropped(scanner_name)
                self._stats.mark_error(scanner_name)
                if general.debug:
                    self._logger.debug(
                        "Falha ao reenviar pacote do scanner '%s' para %s:%d: %s",
                        scanner_name,
                        target.ip,
                        target.port,
                        exc,
                    )
                continue

            if sent != packet_size:
                self._stats.mark_dropped(scanner_name)
                self._stats.mark_error(scanner_name)
                if general.debug:
                    self._logger.debug(
                        "Envio parcial no scanner '%s' para %s:%d: %d/%d bytes",
                        scanner_name,
                        target.ip,
                        target.port,
                        sent,
                        packet_size,
                    )
                continue

            self._stats.mark_forwarded(scanner_name, packet_size)

        self._process_telemetry(runtime, payload, now)

    def _process_telemetry(
        self,
        runtime: ScannerRuntime,
        payload: memoryview,
        now_monotonic: float,
    ) -> None:
        if runtime.interpreter is None:
            return
        if self._telemetry_store is None:
            return

        scanner_name = runtime.config.name
        self._telemetry_packet_counters[scanner_name] += 1
        parse_enabled = (
            self._telemetry_packet_counters[scanner_name]
            % self._config.web.parse_every_n_packets
            == 0
        )
        full_parse = self._config.web.parse_mode == "full"
        try:
            snapshot = runtime.interpreter.feed_datagram(
                payload,
                now_monotonic,
                parse_enabled=parse_enabled,
                full_parse=full_parse,
                invert_scan_direction=runtime.config.invert_scan_direction,
            )
            if snapshot is not None:
                self._telemetry_store.update_snapshot(scanner_name, snapshot)
        except Exception as exc:
            self._telemetry_store.mark_parse_error(scanner_name, str(exc))
            if self._config.general.debug:
                self._logger.debug(
                    "Falha ao interpretar pacote nanoScan3 do scanner '%s': %s",
                    scanner_name,
                    exc,
                )

    def _emit_stats(self, now: float) -> None:
        reports = self._stats.build_reports(
            now=now,
            timeout_sec=self._config.general.scanner_timeout_sec,
        )
        self._logger.info("Resumo periodico do relay UDP:")
        for report in reports:
            self._logger.info(
                "[%s] recebido=%d reenviado=%d descartado=%d erros=%d pps=%.1f throughput=%s sem_dados=%s status=%s",
                report.name,
                report.received_packets,
                report.forwarded_packets,
                report.dropped_packets,
                report.errors,
                report.pps,
                format_bytes_per_second(report.throughput_bytes_per_sec),
                format_duration(report.seconds_since_last_packet),
                report.status,
            )

    @staticmethod
    def _safe_close(sock: socket.socket) -> None:
        try:
            sock.close()
        except Exception:
            pass
