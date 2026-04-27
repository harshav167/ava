"""VoiceMode Connect — remote messaging and presence."""

from .client import ConnectClient, get_client
from .session import ConnectSession, get_connect_session
from .messaging import deliver_message, read_inbox
from .types import ConnectState, Presence, UserInfo
from .users import UserManager
from .watcher import diff_user_state, watch_user_changes

__all__ = [
    "ConnectClient",
    "ConnectSession",
    "ConnectState",
    "Presence",
    "UserInfo",
    "UserManager",
    "deliver_message",
    "diff_user_state",
    "get_client",
    "get_connect_session",
    "read_inbox",
    "watch_user_changes",
]
