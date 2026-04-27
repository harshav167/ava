"""VoiceMode Connect status and presence tool.

Provides a single MCP tool for checking connection status and setting agent
presence (available/away) on the Connect gateway.
"""

from typing import Optional

from voice_mode.connect.session import ConnectStatusRequest, get_connect_session
from voice_mode.server import mcp


@mcp.tool()
async def connect_status(
    set_presence: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    """VoiceMode Connect status and presence.

    Check connection status and who's online, or set your availability.
    Idempotent — safe to call multiple times. Creates user if needed.

    Args:
        set_presence: Optional. Set to "available" (green dot - ready for calls)
            or "away" (amber dot - connected but not accepting calls).
            Omit to just check status.
            Note: "available" requires wake-from-idle capability. In Claude Code,
            create a team first (TeamCreate) to enable this. Without a team,
            presence is downgraded to "away" with guidance on how to enable it.
        username: Optional. Your Connect username (e.g., "cora", "astrid").
            Used to identify which user to register on this WebSocket.
            The PostToolUse hook provides this in its systemMessage.

    Returns:
        Connection status, online contacts, and presence state.

    Examples:
        connect_status()                                         # Check status
        connect_status(set_presence="available", username="cora") # Go available
        connect_status(set_presence="away")                       # Go away
    """

    return await get_connect_session().status(
        ConnectStatusRequest(set_presence=set_presence, username=username)
    )
