#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class SimScanner:
    name: str
    destination_ip: str
    destination_port: int
    source_ip: Optional[str]
    source_port: Optional[int]
    sock: socket.socket
    sent_packets: int = 0
    sent_bytes: int = 0


def parse_scanner_spec(spec: str) -> tuple[str, str, int, Optional[str], Optional[int]]:
    parts = [piece.strip() for piece in spec.split(",")]
    if len(parts) not in (3, 4, 5):
        raise ValueError(
            "Formato de --scanner invalido. Use: "
            "nome,destination_ip,destination_port[,source_ip[,source_port]]"
        )

    name = parts[0]
    destination_ip = parts[1]
    destination_port = int(parts[2])
    source_ip = parts[3] if len(parts) >= 4 and parts[3] else None
    source_port = int(parts[4]) if len(parts) == 5 and parts[4] else None
    return name, destination_ip, destination_port, source_ip, source_port


def build_payload(name: str, cycle: int, packet_idx: int, payload_size: int) -> bytes:
    header = (
        f"scanner={name};cycle={cycle};pkt={packet_idx};mono_ns={time.monotonic_ns()};"
    ).encode("ascii", errors="ignore")
    if len(header) >= payload_size:
        return header[:payload_size]
    return header + (b"X" * (payload_size - len(header)))


def create_scanners(args: argparse.Namespace) -> list[SimScanner]:
    scanner_defs: list[tuple[str, str, int, Optional[str], Optional[int]]] = []
    if args.scanner:
        for spec in args.scanner:
            scanner_defs.append(parse_scanner_spec(spec))
    else:
        for index in range(args.num_scanners):
            scanner_defs.append(
                (
                    f"scanner_{index + 1}",
                    args.base_destination_ip,
                    args.base_destination_port + index,
                    args.source_ip,
                    None,
                )
            )

    scanners: list[SimScanner] = []
    for name, destination_ip, destination_port, source_ip, source_port in scanner_defs:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if source_ip is not None or source_port is not None:
            bind_ip = source_ip if source_ip is not None else "0.0.0.0"
            bind_port = source_port if source_port is not None else 0
            sock.bind((bind_ip, bind_port))
        scanners.append(
            SimScanner(
                name=name,
                destination_ip=destination_ip,
                destination_port=destination_port,
                source_ip=source_ip,
                source_port=source_port,
                sock=sock,
            )
        )
    return scanners


def run_simulation(args: argparse.Namespace) -> None:
    scanners = create_scanners(args)
    if not scanners:
        raise ValueError("Nenhum scanner configurado para simulacao.")

    if args.hz <= 0:
        raise ValueError("--hz deve ser > 0")
    if args.packets_per_cycle <= 0:
        raise ValueError("--packets-per-cycle deve ser > 0")
    if args.payload_size <= 0 or args.payload_size > 65507:
        raise ValueError("--payload-size deve estar entre 1 e 65507")

    print("Simulador iniciado com os scanners abaixo:")
    for scanner in scanners:
        print(
            f"- {scanner.name}: src={scanner.source_ip or 'auto'}:{scanner.source_port or 0} "
            f"-> dst={scanner.destination_ip}:{scanner.destination_port}"
        )

    cycle = 0
    start = time.monotonic()
    interval = 1.0 / args.hz
    next_cycle = start

    try:
        while True:
            now = time.monotonic()
            if args.duration_sec > 0 and (now - start) >= args.duration_sec:
                break

            if now < next_cycle:
                time.sleep(min(next_cycle - now, 0.01))
                continue

            for scanner in scanners:
                for packet_idx in range(args.packets_per_cycle):
                    payload = build_payload(scanner.name, cycle, packet_idx, args.payload_size)
                    scanner.sock.sendto(payload, (scanner.destination_ip, scanner.destination_port))
                    scanner.sent_packets += 1
                    scanner.sent_bytes += len(payload)

            cycle += 1
            next_cycle += interval
            if next_cycle < now - interval:
                next_cycle = now + interval
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario.")
    finally:
        elapsed = max(time.monotonic() - start, 1e-9)
        total_packets = sum(scanner.sent_packets for scanner in scanners)
        total_bytes = sum(scanner.sent_bytes for scanner in scanners)
        print("\nResumo da simulacao:")
        print(f"- Tempo: {elapsed:.2f}s")
        print(f"- Pacotes enviados: {total_packets}")
        print(f"- Vazao media de pacotes: {total_packets / elapsed:.1f} pps")
        print(f"- Bytes enviados: {total_bytes}")
        print(f"- Throughput medio: {total_bytes / elapsed / 1024.0:.1f} KiB/s")
        for scanner in scanners:
            scanner.sock.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulador UDP de scanners industriais.")
    parser.add_argument(
        "--scanner",
        action="append",
        help=(
            "Scanner explicito no formato "
            "nome,destination_ip,destination_port[,source_ip[,source_port]]. "
            "Pode repetir a opcao varias vezes."
        ),
    )
    parser.add_argument("--num-scanners", type=int, default=1, help="Quantidade de scanners auto-gerados (1-4).")
    parser.add_argument("--base-destination-ip", default="127.0.0.1", help="IP de destino base no modo auto.")
    parser.add_argument(
        "--base-destination-port",
        type=int,
        default=21100,
        help="Porta de destino base no modo auto (incrementa +1 por scanner).",
    )
    parser.add_argument(
        "--source-ip",
        default=None,
        help="IP de origem para bind no modo auto (opcional).",
    )
    parser.add_argument("--hz", type=float, default=30.0, help="Ciclos por segundo.")
    parser.add_argument("--packets-per-cycle", type=int, default=4, help="Pacotes por ciclo por scanner.")
    parser.add_argument("--payload-size", type=int, default=512, help="Bytes por pacote.")
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=0.0,
        help="Duracao em segundos (0 = infinito ate Ctrl+C).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.scanner is None and (args.num_scanners < 1 or args.num_scanners > 4):
        parser.error("--num-scanners deve estar entre 1 e 4")

    try:
        run_simulation(args)
    except Exception as exc:
        print(f"Erro no simulador: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
