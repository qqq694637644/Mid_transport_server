from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from .config import load_config
from .errors import MidTransportError
from .health_server import HealthServer
from .logging_config import configure_logging
from .release_assets import ensure_installed
from .xray_config import write_portal_config
from .xray_process import XrayProcessManager

_LOG = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mid Transport Server public-side Xray MT reverse runner")
    parser.add_argument("--config", default="./configs/mid-transport.yaml", help="YAML or JSON config path")
    parser.add_argument(
        "--generate-config-only",
        action="store_true",
        help="read config and generate Xray portal JSON without starting xray",
    )
    parser.add_argument(
        "--xray-config-output",
        default="./configs/xray.portal.generated.json",
        help="generated Xray portal config path",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.logging)
    _LOG.info("config_loaded path=%s release=%s", args.config, config.xray.release_tag)

    generated_config_path = write_portal_config(config, args.xray_config_output)
    _LOG.info("xray_config_generated path=%s", generated_config_path)
    if args.generate_config_only:
        return 0

    installed = ensure_installed(config.xray)
    _LOG.info("asset_installed platform=%s executable=%s", installed.platform_asset.platform_id, installed.executable)

    manager = XrayProcessManager(config, installed, Path(generated_config_path))
    health = HealthServer(config, manager)
    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        _LOG.info("shutdown_signal signum=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    try:
        manager.start()
        health.start()
        while not stop_event.wait(1.0):
            status = manager.snapshot()
            if not status.running and not config.xray.restart_on_exit:
                return status.last_exit_code or 1
    finally:
        health.stop()
        manager.stop()
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except MidTransportError as exc:
        logging.getLogger(__name__).error("startup_failed error=%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
