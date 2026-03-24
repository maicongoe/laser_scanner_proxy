from __future__ import annotations

import ipaddress
import logging
import os
from typing import Optional


def validate_ipv4(value: str, field_name: str) -> str:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(f"Campo '{field_name}' com IP invalido: {value}") from exc

    if parsed.version != 4:
        raise ValueError(f"Campo '{field_name}' deve ser IPv4: {value}")
    return value


def validate_port(value: int, field_name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"Campo '{field_name}' deve ser inteiro.")
    if value < 1 or value > 65535:
        raise ValueError(f"Campo '{field_name}' deve estar entre 1 e 65535: {value}")
    return value


def normalize_log_level(level: str, debug: bool) -> str:
    if debug:
        return "DEBUG"
    normalized = level.upper()
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if normalized not in valid:
        raise ValueError(
            f"log_level invalido: '{level}'. Valores aceitos: {', '.join(sorted(valid))}"
        )
    return normalized


def apply_cpu_affinity(cpu_affinity: Optional[list[int]], logger: logging.Logger) -> None:
    if cpu_affinity is None:
        return

    if not cpu_affinity:
        raise ValueError("cpu_affinity nao pode ser lista vazia.")

    if any((not isinstance(cpu, int) or cpu < 0) for cpu in cpu_affinity):
        raise ValueError("cpu_affinity deve conter apenas inteiros >= 0.")

    unique_cpus = sorted(set(cpu_affinity))
    if len(unique_cpus) != len(cpu_affinity):
        raise ValueError("cpu_affinity nao pode conter CPUs duplicadas.")

    if not hasattr(os, "sched_setaffinity"):
        logger.warning("Afinidade de CPU nao suportada neste sistema.")
        return

    os.sched_setaffinity(0, unique_cpus)
    logger.info("Afinidade de CPU aplicada: %s", ",".join(str(cpu) for cpu in unique_cpus))


def apply_nice(nice_value: Optional[int], logger: logging.Logger) -> None:
    if nice_value is None:
        return

    if not isinstance(nice_value, int):
        raise ValueError("Campo 'nice' deve ser inteiro.")
    if nice_value < -20 or nice_value > 19:
        raise ValueError("Campo 'nice' deve estar entre -20 e 19.")

    new_nice = os.nice(nice_value)
    logger.info("Prioridade nice ajustada. nice atual: %d", new_nice)


def format_duration(seconds: float) -> str:
    if seconds == float("inf"):
        return "nunca"
    if seconds < 1.0:
        return f"{seconds * 1000.0:.0f}ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remainder = seconds - (minutes * 60)
    return f"{minutes}m{remainder:04.1f}s"


def format_bytes_per_second(value: float) -> str:
    if value < 1024.0:
        return f"{value:.0f}B/s"
    if value < 1024.0 * 1024.0:
        return f"{value / 1024.0:.1f}KiB/s"
    return f"{value / (1024.0 * 1024.0):.2f}MiB/s"
