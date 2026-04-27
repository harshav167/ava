"""File-watcher for VoiceMode Connect user changes.

Polls the users directory for symlink changes (new subscriptions,
removed agents, changed targets) and re-announces to the gateway.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("voicemode")


@dataclass(frozen=True)
class UserChangeEvent:
    """A filesystem/user-state change emitted by the Connect watcher."""

    change_type: str
    username: str
    detail: Optional[str] = None


def user_state_events(prev: dict, curr: dict) -> list[UserChangeEvent]:
    """Return typed change events between two user snapshots."""
    return [
        UserChangeEvent(change_type=change_type, username=name, detail=detail)
        for change_type, name, detail in diff_user_state(prev, curr)
    ]


def format_user_change_event(event: UserChangeEvent) -> Optional[str]:
    """Format a watcher event for CLI/log output."""
    if event.change_type == "added":
        return f"  + User added: {event.username}"
    if event.change_type == "removed":
        return f"  - User removed: {event.username}"
    if event.change_type == "subscribed":
        return f"  ^ {event.username} now available (subscribed)"
    if event.change_type == "unsubscribed":
        return f"  v {event.username} no longer available (unsubscribed)"
    if event.change_type == "changed":
        return f"  ~ {event.username} changed"
    return None


async def announce_user_change_events(client, event_count: int, user_count: int) -> bool:
    """Apply watcher events to the gateway through the network adapter."""
    if event_count == 0 or not client.is_connected:
        return False
    await client.send_capabilities_update()
    return True


async def watch_user_changes(
    client,
    user_manager,
    poll_interval: float = 3.0,
    echo: Optional[Callable] = None,
) -> None:
    """Poll users directory for changes and re-announce to gateway.

    Detects:
    - New users added (directory created with meta.json)
    - Users removed (directory deleted)
    - Subscription changes (inbox-live symlink created/removed/changed)

    Args:
        client: ConnectClient instance
        user_manager: UserManager instance
        poll_interval: Seconds between polls (default: 3)
        echo: Optional callback for status messages (e.g., click.echo)
    """
    def _log(msg: str) -> None:
        if echo:
            echo(msg)
        logger.info(msg)

    prev_state = user_manager.snapshot()

    while True:
        await asyncio.sleep(poll_interval)

        try:
            curr_state = user_manager.snapshot()

            if curr_state != prev_state:
                events = user_state_events(prev_state, curr_state)

                for event in events:
                    message = format_user_change_event(event)
                    if message:
                        _log(message)

                if await announce_user_change_events(client, len(events), len(curr_state)):
                    _log(f"  -> Announced {len(curr_state)} user(s) to gateway")

                prev_state = curr_state

        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Don't crash the watcher on transient errors
            logger.debug(f"Watcher error (non-fatal): {e}")


def diff_user_state(
    prev: dict, curr: dict
) -> list[tuple[str, str, Optional[str]]]:
    """Compare two user state snapshots and return a list of changes.

    Returns list of (change_type, username, detail) tuples where
    change_type is one of: added, removed, subscribed, unsubscribed, changed.
    """
    changes = []

    added = set(curr) - set(prev)
    removed = set(prev) - set(curr)
    common = set(curr) & set(prev)

    for name in sorted(added):
        changes.append(("added", name, None))

    for name in sorted(removed):
        changes.append(("removed", name, None))

    for name in sorted(common):
        if curr[name] != prev[name]:
            old_sub = prev[name]["subscribed"]
            new_sub = curr[name]["subscribed"]
            if new_sub and not old_sub:
                changes.append(("subscribed", name, None))
            elif old_sub and not new_sub:
                changes.append(("unsubscribed", name, None))
            else:
                changes.append(("changed", name, None))

    return changes
