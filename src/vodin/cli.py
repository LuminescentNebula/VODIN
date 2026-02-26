from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from .client import create_client_service
from .master import create_master_service


DEFAULT_MASTER_PORT = 9876


def run_client(config_path: str, host: str, port: int | None, log_level: str) -> None:
    service = create_client_service(config_path)
    config = uvicorn.Config(service.app, host=host, port=port or service.client_port, log_level=log_level.lower())
    server = uvicorn.Server(config)
    loop = asyncio.get_event_loop()
    loop.create_task(service.ip_watchdog())
    loop.run_until_complete(server.serve())


def run_master(config_path: str, host: str, port: int, log_level: str) -> None:
    service = create_master_service(config_path)
    uvicorn.run(service.app, host=host, port=port, log_level=log_level.lower())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vodin")
    parser.add_argument("mode", choices=["client", "master"])
    parser.add_argument("--config", required=True, help="Path to role-specific YAML config file")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    log_level = args.log_level.upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    if args.mode == "client":
        run_client(args.config, args.host, args.port, log_level)
        return

    run_master(args.config, args.host, args.port or DEFAULT_MASTER_PORT, log_level)


if __name__ == "__main__":
    main()
