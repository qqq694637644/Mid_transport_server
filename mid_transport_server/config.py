from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .errors import ConfigError

FIXED_RELEASE_TAG = "mt-v26.3.27"
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class XraySettings:
    release_tag: str = FIXED_RELEASE_TAG
    install_root: Path = Path("./runtime/xray-mt")
    auto_download: bool = True
    restart_on_exit: bool = True
    restart_delay_seconds: int = 3


@dataclass(frozen=True)
class PortalSettings:
    reverse_listen_address: str = "0.0.0.0"
    reverse_listen_port: int = 8443
    public_listen_address: str = "0.0.0.0"
    public_main_port: int = 7000
    reverse_credential_id: str = ""
    reverse_outbound_tag: str = "mt-reverse-out"
    reverse_inbound_tag: str = "mt-vless-reverse"
    public_main_inbound_tag: str = "mt-public-main"


@dataclass(frozen=True)
class HealthSettings:
    enabled: bool = True
    listen_address: str = "127.0.0.1"
    listen_port: int = 18080


@dataclass(frozen=True)
class LoggingSettings:
    level: str = "info"
    file: Path = Path("./logs/mid-transport-server.log")


@dataclass(frozen=True)
class AppConfig:
    xray: XraySettings
    portal: PortalSettings
    health: HealthSettings
    logging: LoggingSettings


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("\"") and value.endswith("\""):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _parse_simple_yaml(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse the small two-level YAML shape used by this service.

    This intentionally avoids a PyYAML runtime dependency. It supports comments,
    top-level sections, and scalar key/value pairs, which is all the planned
    config needs.
    """
    result: Dict[str, Dict[str, Any]] = {}
    current_section: str | None = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if not line.startswith((" ", "\t")):
            if not line.endswith(":"):
                raise ConfigError(f"YAML line {line_no}: expected section header")
            current_section = line[:-1].strip()
            if not current_section:
                raise ConfigError(f"YAML line {line_no}: empty section name")
            result.setdefault(current_section, {})
            continue

        if current_section is None:
            raise ConfigError(f"YAML line {line_no}: key outside section")

        stripped = line.strip()
        if ":" not in stripped:
            raise ConfigError(f"YAML line {line_no}: expected key: value")
        key, value = stripped.split(":", 1)
        result[current_section][key.strip()] = _parse_scalar(value)

    return result


def _load_raw(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        raise ConfigError(f"config file does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ConfigError("JSON config root must be an object")
        return loaded
    return _parse_simple_yaml(text)


def _as_int(section: Dict[str, Any], key: str, default: int) -> int:
    value = section.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} must be an integer")


def _as_bool(section: Dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    raise ConfigError(f"{key} must be a boolean")


def _port(value: int, name: str) -> int:
    if value < 1 or value > 65535:
        raise ConfigError(f"{name} must be in 1..65535")
    return value


def _validate_uuid(value: str) -> None:
    if not value or value == "<MT_UUID>":
        raise ConfigError("portal.reverseCredentialId must be set to the shared MT UUID")
    if not _UUID_RE.match(value):
        raise ConfigError("portal.reverseCredentialId must be a valid UUID")
    try:
        uuid.UUID(value)
    except ValueError:
        raise ConfigError("portal.reverseCredentialId must be a valid UUID")


def load_config(path: str | Path) -> AppConfig:
    raw = _load_raw(Path(path))
    xray_raw = raw.get("xray", {}) or {}
    portal_raw = raw.get("portal", {}) or {}
    health_raw = raw.get("health", {}) or {}
    logging_raw = raw.get("logging", {}) or {}

    xray = XraySettings(
        release_tag=str(xray_raw.get("releaseTag", FIXED_RELEASE_TAG)),
        install_root=Path(str(xray_raw.get("installRoot", "./runtime/xray-mt"))),
        auto_download=_as_bool(xray_raw, "autoDownload", True),
        restart_on_exit=_as_bool(xray_raw, "restartOnExit", True),
        restart_delay_seconds=_as_int(xray_raw, "restartDelaySeconds", 3),
    )

    portal = PortalSettings(
        reverse_listen_address=str(portal_raw.get("reverseListenAddress", "0.0.0.0")),
        reverse_listen_port=_port(_as_int(portal_raw, "reverseListenPort", 8443), "portal.reverseListenPort"),
        public_listen_address=str(portal_raw.get("publicListenAddress", "0.0.0.0")),
        public_main_port=_port(_as_int(portal_raw, "publicMainPort", 7000), "portal.publicMainPort"),
        reverse_credential_id=str(portal_raw.get("reverseCredentialId", "")),
        reverse_outbound_tag=str(portal_raw.get("reverseOutboundTag", "mt-reverse-out")),
        reverse_inbound_tag=str(portal_raw.get("reverseInboundTag", "mt-vless-reverse")),
        public_main_inbound_tag=str(portal_raw.get("publicMainInboundTag", "mt-public-main")),
    )

    health = HealthSettings(
        enabled=_as_bool(health_raw, "enabled", True),
        listen_address=str(health_raw.get("listenAddress", "127.0.0.1")),
        listen_port=_port(_as_int(health_raw, "listenPort", 18080), "health.listenPort"),
    )

    logging_settings = LoggingSettings(
        level=str(logging_raw.get("level", "info")),
        file=Path(str(logging_raw.get("file", "./logs/mid-transport-server.log"))),
    )

    validate_config(AppConfig(xray=xray, portal=portal, health=health, logging=logging_settings))
    return AppConfig(xray=xray, portal=portal, health=health, logging=logging_settings)


def validate_config(config: AppConfig) -> None:
    if config.xray.release_tag != FIXED_RELEASE_TAG:
        raise ConfigError(f"xray.releaseTag must be {FIXED_RELEASE_TAG} in the first version")
    if config.xray.restart_delay_seconds < 0:
        raise ConfigError("xray.restartDelaySeconds must be >= 0")
    if config.portal.reverse_listen_port == config.portal.public_main_port:
        raise ConfigError("portal.reverseListenPort and portal.publicMainPort must not conflict")
    _validate_uuid(config.portal.reverse_credential_id)
    if config.health.listen_address != "127.0.0.1":
        raise ConfigError("health.listenAddress must stay 127.0.0.1 in the first version")
    if config.health.listen_port in (config.portal.reverse_listen_port, config.portal.public_main_port):
        raise ConfigError("health.listenPort must not conflict with Xray public ports")
