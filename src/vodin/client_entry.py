from __future__ import annotations

import argparse
import logging

from .cli import run_client


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vodin-client")
    parser.add_argument("--config", default="client.yml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    log_level = args.log_level.upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
    run_client(args.config, args.host, args.port, log_level)


if __name__ == "__main__":
    main()
