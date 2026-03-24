from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import AppConfig, ForwardTarget, GeneralConfig, ScannerConfig, WebConfig
from utils import validate_ipv4, validate_port


class ConfigError(ValueError):
    pass


GENERAL_DEFAULTS: dict[str, Any] = {
    "log_level": "INFO",
    "debug": False,
    "stats_interval_sec": 5.0,
    "recv_socket_buffer_bytes": 1_048_576,
    "send_socket_buffer_bytes": 262_144,
    "max_expected_packet_size": 4096,
    "source_ip_filter_enabled": True,
    "cpu_affinity": None,
    "nice": None,
    "scanner_timeout_sec": 2.0,
    "max_packets_per_socket_event": 128,
}

GENERAL_ALLOWED_KEYS = set(GENERAL_DEFAULTS.keys())
SCANNER_REQUIRED_KEYS = {"name", "enabled", "local_port"}
SCANNER_OPTIONAL_KEYS = {
    "source_ip",
    "destinations",
    "destination_ip",
    "destination_port",
    "invert_scan_direction",
}
SCANNER_ALLOWED_KEYS = SCANNER_REQUIRED_KEYS | SCANNER_OPTIONAL_KEYS

WEB_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "host": "0.0.0.0",
    "port": 8080,
    "max_sample_points": 120,
    "parse_every_n_packets": 1,
    "parse_mode": "full",
}
WEB_ALLOWED_KEYS = set(WEB_DEFAULTS.keys())


def load_config(config_path: str) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"Arquivo de configuracao nao encontrado: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON invalido em {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Configuracao raiz deve ser um objeto JSON.")
    unknown_root = set(raw.keys()) - {"general", "scanners", "web"}
    if unknown_root:
        raise ConfigError(
            f"Campos desconhecidos na raiz da configuracao: {', '.join(sorted(unknown_root))}"
        )

    general_raw = raw.get("general", {})
    scanners_raw = raw.get("scanners")
    web_raw = raw.get("web", {})

    general = _parse_general(general_raw)
    scanners = _parse_scanners(scanners_raw)
    web = _parse_web(web_raw)
    _validate_scanner_relationships(scanners, general.source_ip_filter_enabled)

    return AppConfig(general=general, scanners=scanners, web=web)


def _parse_general(raw: Any) -> GeneralConfig:
    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ConfigError("'general' deve ser um objeto JSON.")

    unknown_keys = set(raw.keys()) - GENERAL_ALLOWED_KEYS
    if unknown_keys:
        raise ConfigError(
            f"Campos desconhecidos em 'general': {', '.join(sorted(unknown_keys))}"
        )

    merged = dict(GENERAL_DEFAULTS)
    merged.update(raw)

    log_level = _ensure_str(merged["log_level"], "general.log_level")
    debug = _ensure_bool(merged["debug"], "general.debug")
    stats_interval_sec = _ensure_float(merged["stats_interval_sec"], "general.stats_interval_sec")
    recv_socket_buffer_bytes = _ensure_int(
        merged["recv_socket_buffer_bytes"],
        "general.recv_socket_buffer_bytes",
    )
    send_socket_buffer_bytes = _ensure_int(
        merged["send_socket_buffer_bytes"],
        "general.send_socket_buffer_bytes",
    )
    max_expected_packet_size = _ensure_int(
        merged["max_expected_packet_size"],
        "general.max_expected_packet_size",
    )
    source_ip_filter_enabled = _ensure_bool(
        merged["source_ip_filter_enabled"],
        "general.source_ip_filter_enabled",
    )
    scanner_timeout_sec = _ensure_float(
        merged["scanner_timeout_sec"],
        "general.scanner_timeout_sec",
    )
    max_packets_per_socket_event = _ensure_int(
        merged["max_packets_per_socket_event"],
        "general.max_packets_per_socket_event",
    )

    cpu_affinity = merged["cpu_affinity"]
    if cpu_affinity is not None:
        if not isinstance(cpu_affinity, list):
            raise ConfigError("general.cpu_affinity deve ser null ou lista de inteiros.")
        for cpu in cpu_affinity:
            if not isinstance(cpu, int) or cpu < 0:
                raise ConfigError("general.cpu_affinity deve conter apenas inteiros >= 0.")

    nice = merged["nice"]
    if nice is not None:
        nice = _ensure_int(nice, "general.nice")
        if nice < -20 or nice > 19:
            raise ConfigError("general.nice deve estar entre -20 e 19.")

    if stats_interval_sec <= 0.0:
        raise ConfigError("general.stats_interval_sec deve ser > 0.")
    if log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(
            "general.log_level invalido. Use DEBUG, INFO, WARNING, ERROR ou CRITICAL."
        )
    if recv_socket_buffer_bytes <= 0:
        raise ConfigError("general.recv_socket_buffer_bytes deve ser > 0.")
    if send_socket_buffer_bytes <= 0:
        raise ConfigError("general.send_socket_buffer_bytes deve ser > 0.")
    if max_expected_packet_size <= 0 or max_expected_packet_size > 65507:
        raise ConfigError("general.max_expected_packet_size deve estar entre 1 e 65507.")
    if scanner_timeout_sec <= 0.0:
        raise ConfigError("general.scanner_timeout_sec deve ser > 0.")
    if max_packets_per_socket_event <= 0:
        raise ConfigError("general.max_packets_per_socket_event deve ser > 0.")

    return GeneralConfig(
        log_level=log_level,
        debug=debug,
        stats_interval_sec=stats_interval_sec,
        recv_socket_buffer_bytes=recv_socket_buffer_bytes,
        send_socket_buffer_bytes=send_socket_buffer_bytes,
        max_expected_packet_size=max_expected_packet_size,
        source_ip_filter_enabled=source_ip_filter_enabled,
        cpu_affinity=cpu_affinity,
        nice=nice,
        scanner_timeout_sec=scanner_timeout_sec,
        max_packets_per_socket_event=max_packets_per_socket_event,
    )


def _parse_scanners(raw: Any) -> list[ScannerConfig]:
    if not isinstance(raw, list):
        raise ConfigError("'scanners' deve ser uma lista.")

    if len(raw) < 1 or len(raw) > 4:
        raise ConfigError("A lista 'scanners' deve conter de 1 a 4 itens.")

    scanners: list[ScannerConfig] = []
    names: set[str] = set()

    for index, item in enumerate(raw):
        context = f"scanners[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{context} deve ser um objeto JSON.")

        unknown = set(item.keys()) - SCANNER_ALLOWED_KEYS
        missing = SCANNER_REQUIRED_KEYS - set(item.keys())
        if unknown:
            raise ConfigError(f"{context} contem campos desconhecidos: {', '.join(sorted(unknown))}")
        if missing:
            raise ConfigError(f"{context} sem campos obrigatorios: {', '.join(sorted(missing))}")

        name = _ensure_str(item["name"], f"{context}.name")
        if not name:
            raise ConfigError(f"{context}.name nao pode ser vazio.")
        if name in names:
            raise ConfigError(f"Nome de scanner duplicado: '{name}'")
        names.add(name)

        enabled = _ensure_bool(item["enabled"], f"{context}.enabled")
        local_port = validate_port(item["local_port"], f"{context}.local_port")
        destinations = _parse_destinations(item, context)

        source_ip_raw = item.get("source_ip")
        source_ip = None
        if source_ip_raw is not None:
            source_ip_text = _ensure_str(source_ip_raw, f"{context}.source_ip")
            if source_ip_text:
                source_ip = validate_ipv4(source_ip_text, f"{context}.source_ip")
        invert_scan_direction = _ensure_bool(
            item.get("invert_scan_direction", False),
            f"{context}.invert_scan_direction",
        )

        scanners.append(
            ScannerConfig(
                name=name,
                enabled=enabled,
                source_ip=source_ip,
                local_port=local_port,
                destinations=destinations,
                invert_scan_direction=invert_scan_direction,
            )
        )

    if not any(scanner.enabled for scanner in scanners):
        raise ConfigError("Pelo menos um scanner deve estar habilitado.")

    return scanners


def _validate_scanner_relationships(
    scanners: list[ScannerConfig],
    source_ip_filter_enabled: bool,
) -> None:
    enabled_scanners = [scanner for scanner in scanners if scanner.enabled]
    grouped_by_port: dict[int, list[ScannerConfig]] = {}
    for scanner in enabled_scanners:
        grouped_by_port.setdefault(scanner.local_port, []).append(scanner)

    for local_port, scanners_on_port in grouped_by_port.items():
        if len(scanners_on_port) == 1:
            continue

        if not source_ip_filter_enabled:
            names = ", ".join(scanner.name for scanner in scanners_on_port)
            raise ConfigError(
                "Conflito de configuracao: varios scanners habilitados na mesma "
                f"porta ({local_port}) com source_ip_filter_enabled=false: {names}"
            )

        missing_source = [scanner.name for scanner in scanners_on_port if scanner.source_ip is None]
        if missing_source:
            names = ", ".join(missing_source)
            raise ConfigError(
                "Para compartilhar a mesma local_port com source_ip_filter_enabled=true, "
                f"todos os scanners precisam de source_ip. Falhando em {local_port}: {names}"
            )

        seen_ips: set[str] = set()
        for scanner in scanners_on_port:
            assert scanner.source_ip is not None
            if scanner.source_ip in seen_ips:
                raise ConfigError(
                    "Conflito de configuracao: scanners duplicados na mesma local_port "
                    f"{local_port} com o mesmo source_ip {scanner.source_ip}"
                )
            seen_ips.add(scanner.source_ip)


def _ensure_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"Campo '{field_name}' deve ser booleano.")
    return value


def _ensure_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"Campo '{field_name}' deve ser string.")
    return value.strip()


def _ensure_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Campo '{field_name}' deve ser inteiro.")
    return value


def _ensure_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"Campo '{field_name}' deve ser numerico.")
    return float(value)


def _parse_web(raw: Any) -> WebConfig:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("'web' deve ser um objeto JSON.")

    unknown_keys = set(raw.keys()) - WEB_ALLOWED_KEYS
    if unknown_keys:
        raise ConfigError(f"Campos desconhecidos em 'web': {', '.join(sorted(unknown_keys))}")

    merged = dict(WEB_DEFAULTS)
    merged.update(raw)

    enabled = _ensure_bool(merged["enabled"], "web.enabled")
    host = _ensure_str(merged["host"], "web.host")
    if not host:
        raise ConfigError("web.host nao pode ser vazio.")
    port = validate_port(merged["port"], "web.port")
    max_sample_points = _ensure_int(merged["max_sample_points"], "web.max_sample_points")
    parse_every_n_packets = _ensure_int(
        merged["parse_every_n_packets"],
        "web.parse_every_n_packets",
    )
    parse_mode = _ensure_str(merged["parse_mode"], "web.parse_mode").lower()
    if max_sample_points <= 0:
        raise ConfigError("web.max_sample_points deve ser > 0.")
    if parse_every_n_packets <= 0:
        raise ConfigError("web.parse_every_n_packets deve ser > 0.")
    if parse_mode not in {"full", "minimal"}:
        raise ConfigError("web.parse_mode deve ser 'full' ou 'minimal'.")

    return WebConfig(
        enabled=enabled,
        host=host,
        port=port,
        max_sample_points=max_sample_points,
        parse_every_n_packets=parse_every_n_packets,
        parse_mode=parse_mode,
    )


def _parse_destinations(item: dict[str, Any], context: str) -> tuple[ForwardTarget, ...]:
    has_list = "destinations" in item
    has_legacy = "destination_ip" in item or "destination_port" in item

    if has_list and has_legacy:
        raise ConfigError(
            f"{context}: use apenas 'destinations' ou o par legado "
            "'destination_ip'/'destination_port', nao ambos."
        )

    if has_list:
        raw_destinations = item["destinations"]
        if not isinstance(raw_destinations, list) or not raw_destinations:
            raise ConfigError(f"{context}.destinations deve ser uma lista nao vazia.")

        parsed: list[ForwardTarget] = []
        seen: set[tuple[str, int]] = set()
        for idx, destination in enumerate(raw_destinations):
            dctx = f"{context}.destinations[{idx}]"
            if not isinstance(destination, dict):
                raise ConfigError(f"{dctx} deve ser um objeto JSON.")
            if set(destination.keys()) != {"ip", "port"}:
                raise ConfigError(f"{dctx} deve conter apenas campos 'ip' e 'port'.")

            ip = validate_ipv4(_ensure_str(destination["ip"], f"{dctx}.ip"), f"{dctx}.ip")
            port = validate_port(destination["port"], f"{dctx}.port")
            key = (ip, port)
            if key in seen:
                raise ConfigError(f"{dctx} duplicado no mesmo scanner: {ip}:{port}")
            seen.add(key)
            parsed.append(ForwardTarget(ip=ip, port=port))

        return tuple(parsed)

    if "destination_ip" not in item or "destination_port" not in item:
        raise ConfigError(
            f"{context}: faltou destino. Informe 'destinations' ou "
            "'destination_ip' + 'destination_port'."
        )

    destination_ip = validate_ipv4(
        _ensure_str(item["destination_ip"], f"{context}.destination_ip"),
        f"{context}.destination_ip",
    )
    destination_port = validate_port(item["destination_port"], f"{context}.destination_port")
    return (ForwardTarget(ip=destination_ip, port=destination_port),)
