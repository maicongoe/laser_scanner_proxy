from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ForwardTarget:
    ip: str
    port: int

    @property
    def address(self) -> tuple[str, int]:
        return (self.ip, self.port)


@dataclass(frozen=True)
class ScannerConfig:
    name: str
    enabled: bool
    local_port: int
    destinations: tuple[ForwardTarget, ...]
    source_ip: Optional[str] = None
    invert_scan_direction: bool = False


@dataclass(frozen=True)
class GeneralConfig:
    log_level: str
    debug: bool
    stats_interval_sec: float
    recv_socket_buffer_bytes: int
    send_socket_buffer_bytes: int
    max_expected_packet_size: int
    source_ip_filter_enabled: bool
    cpu_affinity: Optional[list[int]]
    nice: Optional[int]
    scanner_timeout_sec: float
    max_packets_per_socket_event: int


@dataclass(frozen=True)
class WebConfig:
    enabled: bool
    host: str
    port: int
    max_sample_points: int
    parse_every_n_packets: int
    parse_mode: str


@dataclass(frozen=True)
class AppConfig:
    general: GeneralConfig
    scanners: list[ScannerConfig]
    web: WebConfig

    @property
    def enabled_scanners(self) -> list[ScannerConfig]:
        return [scanner for scanner in self.scanners if scanner.enabled]
