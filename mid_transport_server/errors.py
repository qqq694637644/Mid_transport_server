class MidTransportError(RuntimeError):
    """Base error for startup/config/runtime failures."""


class ConfigError(MidTransportError):
    """Configuration file is missing or invalid."""


class AssetError(MidTransportError):
    """Release asset download, checksum, or extraction failed."""


class XrayProcessError(MidTransportError):
    """Xray config test or subprocess lifecycle failed."""
