from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .config import AppConfig


def build_portal_config(config: AppConfig) -> Dict[str, Any]:
    portal = config.portal
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": portal.reverse_inbound_tag,
                "listen": portal.reverse_listen_address,
                "port": portal.reverse_listen_port,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        {
                            "id": portal.reverse_credential_id,
                            "email": "csharp-main",
                            "reverse": {"tag": portal.reverse_outbound_tag},
                        }
                    ],
                    "decryption": "none",
                },
                "streamSettings": {"network": "tcp", "security": "none"},
            },
            {
                "tag": portal.public_main_inbound_tag,
                "listen": portal.public_listen_address,
                "port": portal.public_main_port,
                "protocol": "dokodemo-door",
                "settings": {
                    "address": "mt.reverse.local",
                    "port": 1,
                    "network": "tcp",
                },
            },
        ],
        "routing": {
            "rules": [
                {
                    "type": "field",
                    "inboundTag": [portal.public_main_inbound_tag],
                    "outboundTag": portal.reverse_outbound_tag,
                }
            ]
        },
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
    }


def write_portal_config(config: AppConfig, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_portal_config(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
