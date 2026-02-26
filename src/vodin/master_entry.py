from __future__ import annotations

import argparse
import logging

from .cli import DEFAULT_MASTER_PORT, run_master


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vodin-master")
    parser.add_argument("--config", default="master.yml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_MASTER_PORT)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    log_level = args.log_level.upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
    run_master(args.config, args.host, args.port, log_level)


if __name__ == "__main__":
    main()
