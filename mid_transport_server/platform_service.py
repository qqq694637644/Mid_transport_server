from __future__ import annotations

from pathlib import Path


def systemd_unit_example(working_directory: str | Path, config_path: str | Path) -> str:
    return f"""[Unit]
Description=Mid Transport Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={Path(working_directory)}
ExecStart=python -m mid_transport_server.main --config {Path(config_path)}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
