from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import AppConfig
from .errors import XrayProcessError
from .release_assets import InstalledAsset

_LOG = logging.getLogger(__name__)


@dataclass
class XrayStatus:
    running: bool = False
    pid: Optional[int] = None
    executable: Optional[str] = None
    config_path: Optional[str] = None
    restart_on_exit: bool = False
    last_exit_code: Optional[int] = None
    last_error: Optional[str] = None
    started_at: Optional[float] = None
    restarts: int = 0


@dataclass
class XrayProcessManager:
    app_config: AppConfig
    installed_asset: InstalledAsset
    xray_config_path: Path
    _process: Optional[subprocess.Popen] = field(default=None, init=False, repr=False)
    _stop_requested: bool = field(default=False, init=False, repr=False)
    _monitor_thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    status: XrayStatus = field(default_factory=XrayStatus, init=False)

    def _base_args(self) -> List[str]:
        return [str(self.installed_asset.executable), "run", "-config", str(self.xray_config_path)]

    def test_config(self, timeout_seconds: int = 30) -> None:
        args = [str(self.installed_asset.executable), "run", "-test", "-config", str(self.xray_config_path)]
        _LOG.info("xray_config_test_start executable=%s config=%s", self.installed_asset.executable, self.xray_config_path)
        try:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - platform subprocess edge
            self.status.last_error = str(exc)
            raise XrayProcessError(f"xray config test failed to execute: {exc}") from exc

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "xray run -test failed").strip()
            self.status.last_error = message
            _LOG.error("xray_config_test_failed returncode=%s error=%s", completed.returncode, message)
            raise XrayProcessError(f"xray config test failed: {message}")
        _LOG.info("xray_config_test_success")

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self.test_config()
        self._stop_requested = False
        args = self._base_args()
        try:
            self._process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:  # pragma: no cover - platform subprocess edge
            self.status.last_error = str(exc)
            raise XrayProcessError(f"failed to start xray: {exc}") from exc

        self.status = XrayStatus(
            running=True,
            pid=self._process.pid,
            executable=str(self.installed_asset.executable),
            config_path=str(self.xray_config_path),
            restart_on_exit=self.app_config.xray.restart_on_exit,
            started_at=time.time(),
        )
        _LOG.info("xray_start pid=%s executable=%s", self._process.pid, self.installed_asset.executable)
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="xray-monitor", daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while self._process is not None:
            proc = self._process
            if proc.stdout is not None:
                for line in proc.stdout:
                    _LOG.info("xray_stdout %s", line.rstrip())
                    if proc.poll() is not None:
                        break
            exit_code = proc.wait()
            self.status.running = False
            self.status.last_exit_code = exit_code
            _LOG.warning("xray_exit code=%s stop_requested=%s", exit_code, self._stop_requested)

            if self._stop_requested or not self.app_config.xray.restart_on_exit:
                return

            self.status.restarts += 1
            _LOG.warning(
                "xray_restart delay_seconds=%s restart_count=%s",
                self.app_config.xray.restart_delay_seconds,
                self.status.restarts,
            )
            time.sleep(self.app_config.xray.restart_delay_seconds)
            try:
                self._process = subprocess.Popen(
                    self._base_args(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self.status.running = True
                self.status.pid = self._process.pid
                self.status.started_at = time.time()
            except Exception as exc:  # pragma: no cover - platform subprocess edge
                self.status.last_error = str(exc)
                _LOG.error("xray_restart_failed error=%s", exc)
                return

    def stop(self, timeout_seconds: int = 10) -> None:
        self._stop_requested = True
        proc = self._process
        if proc is None:
            return
        if proc.poll() is not None:
            self.status.running = False
            return
        _LOG.info("xray_stop pid=%s", proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _LOG.warning("xray_stop_timeout pid=%s killing=true", proc.pid)
            proc.kill()
            proc.wait(timeout=timeout_seconds)
        self.status.running = False
        self.status.last_exit_code = proc.returncode

    def snapshot(self) -> XrayStatus:
        proc = self._process
        if proc is not None:
            self.status.running = proc.poll() is None
            self.status.pid = proc.pid if self.status.running else None
        return self.status
