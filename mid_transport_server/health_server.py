from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Any, Optional

from .config import AppConfig
from .xray_process import XrayProcessManager

_LOG = logging.getLogger(__name__)


class HealthServer:
    def __init__(self, config: AppConfig, process_manager: XrayProcessManager):
        self.config = config
        self.process_manager = process_manager
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.config.health.enabled:
            return
        if self.config.health.listen_address != "127.0.0.1":
            raise ValueError("health server must listen on 127.0.0.1")

        process_manager = self.process_manager
        config = self.config

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
                _LOG.info("health_http " + fmt, *args)

            def _json(self, status_code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                status = process_manager.snapshot()
                if self.path == "/healthz":
                    self._json(
                        200 if status.running else 503,
                        {
                            "ok": status.running,
                            "xrayRunning": status.running,
                            "pid": status.pid,
                            "releaseTag": config.xray.release_tag,
                        },
                    )
                    return
                if self.path == "/status":
                    self._json(
                        200,
                        {
                            "platform": process_manager.installed_asset.platform_asset.platform_id,
                            "xrayExecutable": status.executable,
                            "xrayConfig": status.config_path,
                            "reverseListen": f"{config.portal.reverse_listen_address}:{config.portal.reverse_listen_port}",
                            "publicMainListen": f"{config.portal.public_listen_address}:{config.portal.public_main_port}",
                            "restartOnExit": status.restart_on_exit,
                            "lastExitCode": status.last_exit_code,
                            "lastError": status.last_error,
                            "restarts": status.restarts,
                        },
                    )
                    return
                self._json(404, {"error": "not found"})

        self._server = ThreadingHTTPServer((self.config.health.listen_address, self.config.health.listen_port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="health-server", daemon=True)
        self._thread.start()
        _LOG.info("health_server_start listen=%s:%s", self.config.health.listen_address, self.config.health.listen_port)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
