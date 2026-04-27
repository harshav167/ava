"""User/mailbox management for VoiceMode Connect."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .types import Presence, UserInfo

logger = logging.getLogger("voicemode")

# Lowercase mailbox names with narrow separators keep filesystem paths predictable.
USERNAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
RESERVED_USERNAMES = {".", ".."}


def normalize_username(name: str) -> str:
    """Normalize and validate a Connect username before filesystem use."""
    normalized = name.lower().strip()
    if not normalized:
        raise ValueError("Username cannot be empty")
    if normalized in RESERVED_USERNAMES:
        raise ValueError(f"Invalid username: {name!r}")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("Username must not contain path separators")
    if normalized.startswith("-"):
        raise ValueError("Username must start with a letter or number")
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Username may only contain lowercase letters, numbers, underscores, and hyphens"
        )
    return normalized


def ensure_user_path(base_dir: Path, name: str) -> Path:
    """Return a contained user path after validating the username."""
    normalized = normalize_username(name)
    user_dir = (base_dir / normalized).resolve()
    base_resolved = base_dir.resolve()
    try:
        user_dir.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"Username escapes users directory: {name!r}") from exc
    return user_dir


# Default base directories
VOICEMODE_DIR = Path.home() / ".voicemode"
CONNECT_DIR = VOICEMODE_DIR / "connect"
USERS_DIR = CONNECT_DIR / "users"
CLAUDE_TEAMS_DIR = Path.home() / ".claude" / "teams"


class UserManager:
    """Manages Connect users (mailboxes) on the local filesystem."""

    def __init__(self, host: str, users_dir: Optional[Path] = None):
        self.host = host
        self.users_dir = users_dir or USERS_DIR

    def _user_dir(self, name: str) -> Path:
        return ensure_user_path(self.users_dir, name)

    def add(
        self,
        name: str,
        display_name: str = "",
        subscribe_team: Optional[str] = None,
    ) -> UserInfo:
        """Add a user/mailbox. Creates directory and metadata."""

        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        user_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        meta = {
            "name": normalized_name,
            "display_name": display_name,
            "created": now.isoformat(),
            "last_seen": now.isoformat(),
            "host": self.host,
        }
        meta_path = user_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")

        # Create empty inbox if it doesn't exist
        inbox_path = user_dir / "inbox"
        if not inbox_path.exists():
            inbox_path.touch()

        user = UserInfo(
            name=normalized_name,
            display_name=display_name,
            host=self.host,
            presence=Presence.OFFLINE,
            created=now,
            last_seen=now,
        )

        # Set up subscription if requested
        if subscribe_team:
            self.subscribe(name, subscribe_team)
            user.subscribed_team = subscribe_team

        logger.info(f"Added Connect user: {normalized_name}@{self.host}")
        return user

    def remove(self, name: str) -> bool:
        """Remove a user/mailbox. Removes directory and all contents."""
        import shutil

        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        if not user_dir.exists():
            return False

        # Remove inbox-live symlink first
        self.unsubscribe(name)

        # Remove directory
        shutil.rmtree(user_dir)
        logger.info(f"Removed Connect user: {normalized_name}")
        return True

    def list(self) -> list:
        """List all registered users."""
        users = []
        if not self.users_dir.exists():
            return users

        for user_dir in sorted(self.users_dir.iterdir()):
            if user_dir.is_dir():
                user = self.get(user_dir.name)
                if user:
                    users.append(user)
        return users

    def get(self, name: str) -> Optional[UserInfo]:
        """Get a specific user's info."""

        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        meta_path = user_dir / "meta.json"

        if not meta_path.exists():
            return None

        meta = json.loads(meta_path.read_text())

        subscribed_team = None
        symlink = user_dir / "inbox-live"
        if symlink.is_symlink():
            # Extract team name from symlink target path
            target = str(symlink.readlink())
            parts = target.split("/")
            try:
                teams_idx = parts.index("teams")
                subscribed_team = parts[teams_idx + 1]
            except (ValueError, IndexError):
                pass

        return UserInfo(
            name=meta.get("name", normalized_name),
            display_name=meta.get("display_name", ""),
            host=meta.get("host", self.host),
            presence=Presence.OFFLINE,  # Presence computed elsewhere
            subscribed_team=subscribed_team,
            created=datetime.fromisoformat(meta["created"]) if "created" in meta else None,
            last_seen=datetime.fromisoformat(meta["last_seen"]) if "last_seen" in meta else None,
        )

    def ensure_inbox(self, name: str) -> Path:
        """Ensure the user's inbox file exists and return it."""
        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        user_dir.mkdir(parents=True, exist_ok=True)
        inbox_path = user_dir / "inbox"
        if not inbox_path.exists():
            inbox_path.touch()
            logger.info(f"Created inbox for user: {normalized_name}")
        return inbox_path

    def inbox_live_path(self, name: str) -> Path:
        """Return the user's inbox-live symlink path."""
        normalized_name = normalize_username(name)
        return self._user_dir(normalized_name) / "inbox-live"

    def team_inbox_path(self, team_name: str) -> Path:
        """Return the Claude team inbox path for wake-from-idle delivery."""
        return CLAUDE_TEAMS_DIR / team_name / "inboxes" / "team-lead.json"

    def link_inbox_to_team(self, name: str, team_name: str) -> bool:
        """Link a user's inbox-live to an existing Claude team inbox.

        Unlike subscribe(), this validates that the team already exists so
        available presence only succeeds for the current session's real team.
        """
        team_dir = CLAUDE_TEAMS_DIR / team_name
        if not team_dir.exists():
            logger.debug(f"Team directory doesn't exist: {team_dir}")
            return False

        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        user_dir.mkdir(parents=True, exist_ok=True)
        symlink = user_dir / "inbox-live"
        target = self.team_inbox_path(team_name)
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            if symlink.is_symlink():
                current_target = symlink.readlink()
                if current_target != target:
                    logger.info(
                        "Removing stale inbox-live symlink "
                        f"(points to {current_target}, expected {target})"
                    )
                    symlink.unlink()
            elif symlink.exists():
                return False

            if not symlink.is_symlink():
                symlink.symlink_to(target)
                logger.info(f"Created inbox-live symlink: {symlink} -> {target}")
            return True
        except OSError as exc:
            logger.warning(f"Failed to create inbox-live symlink: {exc}")
            return False

    def subscribe(self, name: str, team_name: str) -> Path:
        """Create inbox-live symlink for a user.

        Handles stale symlinks and directories safely using rename-to-stale pattern.
        """
        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        user_dir.mkdir(parents=True, exist_ok=True)

        symlink = user_dir / "inbox-live"
        target = CLAUDE_TEAMS_DIR / team_name / "inboxes" / "team-lead.json"

        # Ensure target parent directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        # Handle existing path at symlink location
        if symlink.is_symlink():
            current_target = symlink.resolve()
            if current_target == target.resolve():
                logger.debug(f"inbox-live for {name} already points to correct target")
                return symlink
            # Stale symlink — update it
            logger.info(f"Updating stale inbox-live symlink for {name}")
            symlink.unlink()
        elif symlink.exists():
            # Something unexpected at the symlink path — rename it safely
            stale_name = f"inbox-live.stale-{int(time.time())}"
            stale_path = user_dir / stale_name
            logger.warning(f"Found unexpected file at inbox-live for {name}, renaming to {stale_name}")
            symlink.rename(stale_path)

        symlink.symlink_to(target)
        logger.info(f"Subscribed {normalized_name} to team {team_name}")
        return symlink

    def unsubscribe(self, name: str) -> bool:
        """Remove inbox-live symlink for a user."""
        normalized_name = normalize_username(name)
        symlink = self._user_dir(normalized_name) / "inbox-live"
        if symlink.is_symlink():
            symlink.unlink()
            logger.info(f"Unsubscribed {normalized_name}")
            return True
        return False

    def is_subscribed(self, name: str) -> bool:
        """Check if a user has an active (non-stale) inbox-live symlink."""
        normalized_name = normalize_username(name)
        symlink = self._user_dir(normalized_name) / "inbox-live"
        if not symlink.is_symlink():
            return False
        # Check if the target exists (not stale)
        try:
            target = symlink.resolve()
            return target.parent.exists()
        except OSError:
            return False

    def get_presence(self, name: str):
        """Determine presence for a user."""

        normalized_name = normalize_username(name)
        user_dir = self._user_dir(normalized_name)
        if not user_dir.exists():
            return Presence.OFFLINE
        if self.is_subscribed(name):
            return Presence.AVAILABLE
        return Presence.ONLINE

    def snapshot(self) -> dict:
        """Capture current state of all users and their symlinks.

        Returns a dict keyed by username with display_name, symlink_target,
        and subscribed status. Used by the file-watcher to detect changes.
        """
        state = {}
        for user in self.list():
            user_dir = self._user_dir(user.name)
            symlink = user_dir / "inbox-live"
            if symlink.is_symlink():
                try:
                    target = str(symlink.readlink())
                except OSError:
                    target = None
            else:
                target = None
            state[user.name] = {
                "display_name": user.display_name,
                "symlink_target": target,
                "subscribed": user.subscribed_team is not None,
            }
        return state
