from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScannerStats:
    received_packets: int = 0
    forwarded_packets: int = 0
    received_bytes: int = 0
    forwarded_bytes: int = 0
    dropped_packets: int = 0
    errors: int = 0
    last_receive_monotonic: float | None = None


@dataclass(frozen=True)
class ScannerStatsReport:
    name: str
    received_packets: int
    forwarded_packets: int
    received_bytes: int
    forwarded_bytes: int
    dropped_packets: int
    errors: int
    pps: float
    throughput_bytes_per_sec: float
    seconds_since_last_packet: float
    status: str


class StatsRegistry:
    def __init__(self, scanner_names: list[str]) -> None:
        self._order = list(scanner_names)
        self._stats = {name: ScannerStats() for name in scanner_names}
        self._last_report_monotonic = 0.0
        self._last_rx_packets_snapshot = {name: 0 for name in scanner_names}
        self._last_rx_bytes_snapshot = {name: 0 for name in scanner_names}

    def mark_received(self, scanner_name: str, packet_size: int, now: float) -> None:
        stats = self._stats[scanner_name]
        stats.received_packets += 1
        stats.received_bytes += packet_size
        stats.last_receive_monotonic = now

    def mark_forwarded(self, scanner_name: str, packet_size: int) -> None:
        stats = self._stats[scanner_name]
        stats.forwarded_packets += 1
        stats.forwarded_bytes += packet_size

    def mark_dropped(self, scanner_name: str) -> None:
        self._stats[scanner_name].dropped_packets += 1

    def mark_error(self, scanner_name: str) -> None:
        self._stats[scanner_name].errors += 1

    def build_reports(self, now: float, timeout_sec: float) -> list[ScannerStatsReport]:
        if self._last_report_monotonic == 0.0:
            elapsed = 1.0
        else:
            elapsed = max(now - self._last_report_monotonic, 1e-9)

        reports: list[ScannerStatsReport] = []
        for name in self._order:
            stats = self._stats[name]
            delta_packets = stats.received_packets - self._last_rx_packets_snapshot[name]
            delta_bytes = stats.received_bytes - self._last_rx_bytes_snapshot[name]
            pps = delta_packets / elapsed
            throughput = delta_bytes / elapsed

            if stats.last_receive_monotonic is None:
                silent_for = float("inf")
                status = "TIMEOUT"
            else:
                silent_for = max(0.0, now - stats.last_receive_monotonic)
                status = "OK" if silent_for <= timeout_sec else "TIMEOUT"

            reports.append(
                ScannerStatsReport(
                    name=name,
                    received_packets=stats.received_packets,
                    forwarded_packets=stats.forwarded_packets,
                    received_bytes=stats.received_bytes,
                    forwarded_bytes=stats.forwarded_bytes,
                    dropped_packets=stats.dropped_packets,
                    errors=stats.errors,
                    pps=pps,
                    throughput_bytes_per_sec=throughput,
                    seconds_since_last_packet=silent_for,
                    status=status,
                )
            )

            self._last_rx_packets_snapshot[name] = stats.received_packets
            self._last_rx_bytes_snapshot[name] = stats.received_bytes

        self._last_report_monotonic = now
        return reports
