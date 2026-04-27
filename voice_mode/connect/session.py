"""Service boundary for VoiceMode Connect status, identity, and presence."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config as connect_config
from .client import ConnectClient
from .types import UserInfo
from .users import normalize_username

logger = logging.getLogger("voicemode")


@dataclass(frozen=True)
class ConnectStatusRequest:
    """Request model for the connect_status MCP tool boundary."""

    set_presence: Optional[str] = None
    username: Optional[str] = None
    connect_timeout: float = 10.0


@dataclass
class PresenceUpdateResult:
    """Computed presence update result before user-facing formatting."""

    requested_presence: str
    effective_presence: str
    users: list[UserInfo] = field(default_factory=list)
    downgraded_from_available: bool = False
    error: Optional[str] = None


def format_presence_result(result: PresenceUpdateResult) -> str:
    """Format a computed presence update result for MCP output."""

    if result.error:
        return result.error
    if result.downgraded_from_available:
        return (
            "Set to Away (amber dot) instead of Available.\n"
            "Available requires wake-from-idle capability.\n"
            "To enable: create a team with TeamCreate, then set presence again.\n"
            "Messages will be delivered when you're active."
        )
    if result.effective_presence == "available":
        user_names = ", ".join(user.display_name or user.name for user in result.users)
        return (
            "Now Available (green dot). Users can call you.\n"
            f"Registered as: {user_names}\n"
            "Wake-from-idle: enabled (team inbox linked)"
        )
    return "Now Away (amber dot). Messages will queue for later."


def format_connect_disabled() -> str:
    return (
        "VoiceMode Connect is disabled.\n"
        "Set VOICEMODE_CONNECT_ENABLED=true in .voicemode.env to enable."
    )


def format_connect_failure(status_message: str) -> str:
    return (
        "Failed to connect to VoiceMode Connect gateway.\n"
        f"Status: {status_message}\n"
        "Run: voicemode connect auth login\n"
        "Check: voicemode connect auth status"
    )


class ConnectSessionIdentity:
    """Reads Claude session identity data from the local session store."""

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        environ: Optional[dict[str, str]] = None,
    ):
        self.sessions_dir = sessions_dir or Path.home() / ".voicemode" / "sessions"
        self.environ = environ if environ is not None else os.environ

    def read(self, agent_name: Optional[str] = None) -> dict:
        """Read session identity data using env var lookup, then agent scan."""

        session_id = self.environ.get("CLAUDE_SESSION_ID", "")
        if session_id:
            session_file = self.sessions_dir / f"{session_id}.json"
            if session_file.exists():
                try:
                    data = json.loads(session_file.read_text())
                    logger.info(
                        "Connect session identity: found via CLAUDE_SESSION_ID: "
                        f"{session_file.name}"
                    )
                    return data
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"Failed to read session file: {exc}")

        if agent_name and self.sessions_dir.exists():
            try:
                session_files = sorted(
                    self.sessions_dir.glob("*.json"),
                    key=lambda file: file.stat().st_mtime,
                    reverse=True,
                )
                for session_file in session_files[:10]:
                    try:
                        data = json.loads(session_file.read_text())
                    except (json.JSONDecodeError, OSError):
                        continue
                    if data.get("agent_name") == agent_name:
                        logger.info(
                            "Connect session identity: found via scan for "
                            f"{agent_name}: {session_file.name}"
                        )
                        return data
            except OSError as exc:
                logger.warning(f"Failed to scan sessions directory: {exc}")

        if not session_id:
            logger.info(
                "Connect session identity: CLAUDE_SESSION_ID not set"
                + (f", no session found for agent {agent_name}" if agent_name else "")
            )
        return {}

    def discover_username(self) -> Optional[str]:
        """Return the current agent name from session identity, if available."""

        username = self.read().get("agent_name", "") or None
        if username:
            logger.info(f"Auto-discovered username from session: {username}")
        return username


class ConnectPresenceSession:
    """Presence/session identity boundary over the fakeable Connect client."""

    def __init__(
        self,
        client: ConnectClient,
        identity: Optional[ConnectSessionIdentity] = None,
    ):
        self.client = client
        self.identity = identity or ConnectSessionIdentity()

    async def ensure_user_registered(self, username: Optional[str] = None) -> list:
        """Ensure this process has a registered Connect user."""

        if self.client._primary_user:
            user = self.client.user_manager.get(self.client._primary_user.name)
            if user:
                self.client.user_manager.ensure_inbox(user.name)
                return [user]

        if username:
            try:
                username = normalize_username(username)
            except ValueError as exc:
                return [f"Invalid username: {exc}"]

            user = self.client.user_manager.get(username)
            if not user:
                display_name = connect_config.get_agent_name() or username
                user = self.client.user_manager.add(
                    name=username,
                    display_name=display_name,
                )
                logger.info(f"Created Connect user: {username}")

            self.client.user_manager.ensure_inbox(username)
            await self.client.register_user(user)
            logger.info(f"Registered user {username} on MCP server WebSocket")
            return [user]

        all_users = self.client.user_manager.list()
        if all_users:
            user = all_users[0]
            self.client.user_manager.ensure_inbox(user.name)
            await self.client.register_user(user)
            logger.info(f"Auto-registered user {user.name} on MCP server WebSocket")
            return all_users

        configured = connect_config.get_preconfigured_users()
        if configured:
            users = []
            for name in configured:
                user = self.client.user_manager.get(name)
                if user:
                    self.client.user_manager.ensure_inbox(user.name)
                    users.append(user)
            if users:
                await self.client.register_user(users[0])
                return users

        return []

    async def set_presence(
        self,
        presence: str,
        username: Optional[str] = None,
    ) -> str:
        """Set presence and return user-facing MCP text."""

        result = await self.compute_presence_update(presence, username=username)
        return format_presence_result(result)

    async def compute_presence_update(
        self,
        presence: str,
        username: Optional[str] = None,
    ) -> PresenceUpdateResult:
        """Compute and send a presence update without formatting concerns."""

        requested_presence = presence.lower().strip()
        effective_presence = requested_presence
        if effective_presence in ("unavailable", "busy", "dnd"):
            effective_presence = "away"

        if effective_presence not in ("available", "away"):
            return PresenceUpdateResult(
                requested_presence=requested_presence,
                effective_presence=effective_presence,
                error=(
                    f"Invalid presence: '{requested_presence}'. "
                    "Use 'available' (green dot) or 'away' (amber dot)."
                ),
            )

        if not self.client.is_connected:
            return PresenceUpdateResult(
                requested_presence=requested_presence,
                effective_presence=effective_presence,
                error=(
                    "Not connected to VoiceMode Connect gateway. "
                    "Cannot set presence while disconnected."
                ),
            )

        users = await self.ensure_user_registered(username)
        if users and isinstance(users[0], str):
            return PresenceUpdateResult(
                requested_presence=requested_presence,
                effective_presence=effective_presence,
                error=users[0],
            )
        if not users:
            return PresenceUpdateResult(
                requested_presence=requested_presence,
                effective_presence=effective_presence,
                error="No Connect users found. Pass username parameter to register.",
            )

        downgraded_from_available = False
        if effective_presence == "available":
            effective_presence, downgraded_from_available = self._resolve_available_presence(users)

        try:
            await self.client.send_presence_update(users, effective_presence)
        except Exception as exc:
            logger.error(f"Failed to set presence: {exc}")
            return PresenceUpdateResult(
                requested_presence=requested_presence,
                effective_presence=effective_presence,
                users=users,
                downgraded_from_available=downgraded_from_available,
                error=f"Failed to set presence: {exc}",
            )

        return PresenceUpdateResult(
            requested_presence=requested_presence,
            effective_presence=effective_presence,
            users=users,
            downgraded_from_available=downgraded_from_available,
        )

    def _resolve_available_presence(self, users: list[UserInfo]) -> tuple[str, bool]:
        """Validate wake-from-idle state before allowing available presence."""

        user = users[0]
        session_data = self.identity.read(agent_name=user.name)
        team_name = session_data.get("team_name", "")
        logger.info(
            "Connect presence: session_data=%s, team_name=%r",
            session_data,
            team_name,
        )

        inbox_live = self.client.user_manager.inbox_live_path(user.name)
        if not team_name:
            if inbox_live.is_symlink():
                try:
                    target = inbox_live.readlink()
                except OSError:
                    target = "<unreadable>"
                logger.info(
                    "inbox-live symlink exists but not owned by this session "
                    f"(no team_name): {inbox_live} -> {target}"
                )
            logger.info(
                "Downgraded presence from available to away "
                "(no team_name in current session)"
            )
            return "away", True

        if self.client.user_manager.link_inbox_to_team(user.name, team_name):
            logger.info(f"Wake-from-idle enabled: {user.name} -> team {team_name}")
        else:
            logger.info("Connect presence: link_inbox_to_team returned False")

        if not inbox_live.is_symlink():
            logger.info(
                "Downgraded presence from available to away "
                "(inbox-live symlink could not be created)"
            )
            return "away", True

        return "available", False


class ConnectService:
    """Application service for the connect_status MCP tool."""

    def __init__(
        self,
        client: Optional[ConnectClient] = None,
        identity: Optional[ConnectSessionIdentity] = None,
        presence_session: Optional[ConnectPresenceSession] = None,
    ):
        if client is None:
            from .client import get_client

            client = get_client()
        self.client = client
        self.identity = identity or ConnectSessionIdentity()
        self.presence_session = presence_session or ConnectPresenceSession(
            client,
            identity=self.identity,
        )

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    @property
    def is_connecting(self) -> bool:
        return self.client.is_connecting

    @property
    def status_message(self) -> str:
        return self.client.status_message

    async def connect(self) -> None:
        await self.client.connect()

    async def disconnect(self) -> None:
        await self.client.disconnect()

    async def wait_connected(self, timeout: float = 10.0) -> bool:
        return await self.client.wait_connected(timeout=timeout)

    def get_status_text(self) -> str:
        return self.client.get_status_text()

    async def ensure_user_registered(self, username: Optional[str] = None) -> list:
        return await self.presence_session.ensure_user_registered(username)

    async def set_presence(self, presence: str, username: Optional[str] = None) -> str:
        return await self.presence_session.set_presence(presence, username=username)

    async def status(self, request: ConnectStatusRequest) -> str:
        """Handle connect_status without leaking tool concerns into adapters."""

        if not connect_config.is_enabled():
            return format_connect_disabled()

        if not self.is_connected and not self.is_connecting:
            logger.info("Connect: lazy WebSocket connect on first connect_status call")
            await self.connect()
            connected = await self.wait_connected(timeout=request.connect_timeout)
            if not connected:
                return format_connect_failure(self.status_message)

        if request.set_presence:
            username = request.username or self.identity.discover_username()
            return await self.set_presence(request.set_presence, username=username)

        return self.get_status_text()


class ConnectSession(ConnectService):
    """Compatibility name for the Connect service/session boundary."""


# Compatibility helper for older tests and imports.
def _get_session_data(agent_name: Optional[str] = None) -> dict:
    return ConnectSessionIdentity().read(agent_name=agent_name)


def get_connect_session() -> ConnectSession:
    return ConnectSession()
