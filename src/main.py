from __future__ import annotations

import argparse
import signal
import sys

from config_loader import ConfigError, load_config
from logger_setup import setup_logger
from telemetry_store import TelemetryStore
from udp_relay import UdpRelay
from utils import apply_cpu_affinity, apply_nice
from web_server import TelemetryWebServer


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Relay/Fan-out UDP para laser scanners industriais.",
    )
    parser.add_argument(
        "--config",
        default="config/relay_config.json",
        help="Caminho para o arquivo JSON de configuracao.",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Valida a configuracao e sai sem iniciar o relay.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Erro de configuracao: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Erro ao ler arquivo de configuracao: {exc}", file=sys.stderr)
        return 2

    logger = setup_logger(config.general.log_level, config.general.debug)

    if args.validate_config:
        logger.info("Configuracao valida: %s", args.config)
        return 0

    try:
        apply_cpu_affinity(config.general.cpu_affinity, logger)
        apply_nice(config.general.nice, logger)
    except Exception as exc:
        logger.error("Falha ao aplicar afinidade/nice: %s", exc)
        return 3

    telemetry_store = TelemetryStore([scanner.name for scanner in config.enabled_scanners])
    telemetry_web_server = TelemetryWebServer(config.web, telemetry_store, logger)

    try:
        telemetry_web_server.start()
    except Exception as exc:
        logger.error("Falha ao iniciar servidor web de telemetria: %s", exc)
        return 6

    relay = UdpRelay(config, logger, telemetry_store=telemetry_store)

    def _signal_handler(signum: int, _frame: object) -> None:
        logger.info("Sinal recebido (%d). Encerrando de forma limpa...", signum)
        relay.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        relay.run()
    except KeyboardInterrupt:
        logger.info("Interrupcao via teclado recebida.")
        relay.stop()
    except RuntimeError as exc:
        logger.error("Falha ao iniciar relay: %s", exc)
        return 4
    except Exception:
        logger.exception("Erro inesperado no relay.")
        return 5
    finally:
        telemetry_web_server.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
