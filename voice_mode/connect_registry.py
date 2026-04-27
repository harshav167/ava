"""
DEPRECATED: Use voice_mode.connect instead.

This module is a thin shim retained for backward compatibility.
All functionality has moved to the voice_mode.connect package.

    from voice_mode.connect.client import ConnectClient, DeviceInfo
    from voice_mode.connect import get_client
"""

import warnings

warnings.warn(
    "voice_mode.connect_registry is deprecated. "
    "Use voice_mode.connect.client (ConnectClient, DeviceInfo) instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export symbols that consumers may still reference
from voice_mode.connect.client import ConnectClient as ConnectRegistry  # noqa: F401, E402
from voice_mode.connect.client import DeviceInfo  # noqa: F401, E402
from voice_mode.connect.client import get_client  # noqa: E402

# Singleton shim — delegates to the new get_client()
connect_registry = get_client()
