"""Tests for VoiceMode Connect status/session service boundaries."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_mode.connect.session import (
    ConnectPresenceSession,
    ConnectService,
    ConnectSessionIdentity,
    ConnectStatusRequest,
    _get_session_data,
)
from voice_mode.connect.types import UserInfo
from voice_mode.connect.users import UserManager
from voice_mode.tools.connect_status import connect_status as connect_status_tool

# FastMCP 2.x wraps tools as FunctionTool (with .fn attribute),
# FastMCP 3.x returns the raw function.
_connect_status_fn = getattr(connect_status_tool, "fn", connect_status_tool)


def _make_user(name="cora", display_name="Cora 7", host="test-host"):
    return UserInfo(name=name, display_name=display_name, host=host)


@pytest.fixture
def user_manager(tmp_path):
    users_dir = tmp_path / ".voicemode" / "connect" / "users"
    users_dir.mkdir(parents=True)
    return UserManager(host="test-host", users_dir=users_dir)


@pytest.fixture
def mock_client(user_manager):
    """Create a mock ConnectClient with a real temp-backed UserManager."""
    client = MagicMock()
    client.is_connected = True
    client.is_connecting = False
    client.status_message = "Connected"
    client.connect = AsyncMock()
    client.wait_connected = AsyncMock(return_value=True)
    client._primary_user = None
    client._ws = AsyncMock()
    client.user_manager = user_manager
    client.get_status_text.return_value = "VoiceMode Connect: Connected"
    client.register_user = AsyncMock()

    async def send_presence_update(users, presence=None):
        entries = []
        for user in users:
            wire_presence = presence
            if wire_presence is None:
                wire_presence = user_manager.get_presence(user.name).value
            elif wire_presence != "available":
                wire_presence = "online"
            entries.append({
                "name": user.name,
                "host": user.host,
                "display_name": user.display_name,
                "presence": wire_presence,
            })
        await client._ws.send(json.dumps({
            "type": "capabilities_update",
            "users": entries,
            "platform": "claude-code",
        }))

    client.send_presence_update = AsyncMock(side_effect=send_presence_update)
    return client


def _service(client, sessions_dir=None, environ=None):
    identity = ConnectSessionIdentity(
        sessions_dir=sessions_dir or Path("/tmp/nonexistent-voicemode-sessions"),
        environ=environ or {},
    )
    return ConnectService(client=client, identity=identity)


class TestConnectStatusTool:
    @pytest.mark.asyncio
    async def test_delegates_to_connect_service(self):
        """connect_status is a thin wrapper around the session/service API."""
        service = MagicMock()
        service.status = AsyncMock(return_value="ok")

        with patch(
            "voice_mode.tools.connect_status.get_connect_session",
            return_value=service,
        ):
            result = await _connect_status_fn(set_presence="away", username="cora")

        assert result == "ok"
        request = service.status.await_args.args[0]
        assert isinstance(request, ConnectStatusRequest)
        assert request.set_presence == "away"
        assert request.username == "cora"


class TestConnectStatusDisabled:
    @pytest.mark.asyncio
    async def test_returns_disabled_message(self, mock_client):
        """connect_status returns helpful message when Connect is disabled."""
        service = _service(mock_client)
        with patch("voice_mode.connect.config.is_enabled", return_value=False):
            result = await service.status(ConnectStatusRequest())

        assert "VoiceMode Connect is disabled" in result
        assert "VOICEMODE_CONNECT_ENABLED=true" in result


class TestConnectStatusConnection:
    @pytest.mark.asyncio
    async def test_triggers_connect_when_disconnected(self, mock_client):
        """Status calls client.connect() when not connected."""
        mock_client.is_connected = False
        mock_client.is_connecting = False
        service = _service(mock_client)

        with patch("voice_mode.connect.config.is_enabled", return_value=True):
            await service.status(ConnectStatusRequest())

        mock_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_lazy_connect_returns_guidance(self, mock_client):
        mock_client.is_connected = False
        mock_client.is_connecting = False
        mock_client.wait_connected.return_value = False
        mock_client.status_message = "Not connected (no credentials)"
        service = _service(mock_client)

        with patch("voice_mode.connect.config.is_enabled", return_value=True):
            result = await service.status(ConnectStatusRequest())

        assert "Failed to connect to VoiceMode Connect gateway" in result
        assert "voicemode connect auth login" in result

    @pytest.mark.asyncio
    async def test_returns_status_text_when_no_presence(self, mock_client):
        """Status returns status text when set_presence is not given."""
        service = _service(mock_client)

        with patch("voice_mode.connect.config.is_enabled", return_value=True):
            result = await service.status(ConnectStatusRequest())

        assert result == "VoiceMode Connect: Connected"
        mock_client.get_status_text.assert_called_once()


class TestSetPresenceValidation:
    @pytest.mark.asyncio
    async def test_invalid_presence_rejected(self, mock_client):
        result = await _service(mock_client).set_presence("invisible")
        assert "Invalid presence" in result
        assert "'invisible'" in result
        assert "available" in result
        assert "away" in result

    @pytest.mark.asyncio
    async def test_random_string_rejected(self, mock_client):
        result = await _service(mock_client).set_presence("online")
        assert "Invalid presence" in result

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self, mock_client):
        mock_client.is_connected = False
        result = await _service(mock_client).set_presence("available")
        assert "Not connected" in result
        assert "Cannot set presence" in result


class TestAliasMapping:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("alias", ["busy", "dnd", "unavailable"])
    async def test_alias_maps_to_away(self, mock_client, alias):
        mock_client.user_manager.add("cora", display_name="Cora 7")
        result = await _service(mock_client).set_presence(alias)
        assert "Away" in result


class TestEnsureUserRegistered:
    @pytest.mark.asyncio
    async def test_already_registered_returns_existing(self, mock_client):
        user = mock_client.user_manager.add("cora", display_name="Cora 7")
        mock_client._primary_user = user

        result = await _service(mock_client).ensure_user_registered()

        assert result == [user]
        mock_client.register_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_username_finds_existing(self, mock_client):
        user = mock_client.user_manager.add("cora", display_name="Cora 7")

        result = await _service(mock_client).ensure_user_registered(username="cora")

        assert result == [user]
        mock_client.register_user.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_explicit_username_creates_when_missing(self, mock_client):
        with patch("voice_mode.connect.config.get_agent_name", return_value="NewBot"):
            result = await _service(mock_client).ensure_user_registered(username="newbot")

        user = result[0]
        assert user.name == "newbot"
        assert user.display_name == "NewBot"
        assert (mock_client.user_manager._user_dir("newbot") / "inbox").exists()
        mock_client.register_user.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_invalid_username_rejected(self, mock_client):
        result = await _service(mock_client).ensure_user_registered(username="../escape")
        assert result == ["Invalid username: Username must not contain path separators"]
        mock_client.register_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_username_normalizes_case(self, mock_client):
        mock_client.user_manager.add("cora")

        await _service(mock_client).ensure_user_registered(username="  CORA  ")

        registered_user = mock_client.register_user.await_args.args[0]
        assert registered_user.name == "cora"

    @pytest.mark.asyncio
    async def test_auto_discover_users(self, mock_client):
        user = mock_client.user_manager.add("cora")

        result = await _service(mock_client).ensure_user_registered()

        assert result == [user]
        mock_client.register_user.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_preconfigured_users_fallback(self, mock_client):
        user = mock_client.user_manager.add("alice")
        mock_client.user_manager.remove("alice")
        # Recreate metadata lookup path without list() discovering users.
        mock_client.user_manager.get = MagicMock(return_value=user)
        mock_client.user_manager.list = MagicMock(return_value=[])

        with patch("voice_mode.connect.config.get_preconfigured_users", return_value=["alice"]):
            result = await _service(mock_client).ensure_user_registered()

        assert result == [user]
        mock_client.register_user.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_no_users_found_returns_empty(self, mock_client):
        with patch("voice_mode.connect.config.get_preconfigured_users", return_value=[]):
            result = await _service(mock_client).ensure_user_registered()

        assert result == []
        mock_client.register_user.assert_not_awaited()


class TestSetPresenceMissingUser:
    @pytest.mark.asyncio
    async def test_no_users_returns_error(self, mock_client):
        with patch("voice_mode.connect.config.get_preconfigured_users", return_value=[]):
            result = await _service(mock_client).set_presence("available")

        assert "No Connect users found" in result


class TestSetPresenceAvailable:
    @pytest.mark.asyncio
    async def test_available_downgrades_without_wake(self, mock_client):
        mock_client.user_manager.add("cora", display_name="Cora 7")

        result = await _service(mock_client).set_presence("available")

        assert "Set to Away" in result
        assert "instead of Available" in result
        assert "TeamCreate" in result
        mock_client._ws.send.assert_awaited_once()
        sent = json.loads(mock_client._ws.send.call_args[0][0])
        assert sent["users"][0]["presence"] == "online"

    @pytest.mark.asyncio
    async def test_available_succeeds_with_wake(self, mock_client, tmp_path, monkeypatch):
        import voice_mode.connect.users as users_mod

        monkeypatch.setattr(users_mod, "CLAUDE_TEAMS_DIR", tmp_path / ".claude" / "teams")
        team_dir = users_mod.CLAUDE_TEAMS_DIR / "my-team" / "inboxes"
        team_dir.mkdir(parents=True)

        mock_client.user_manager.add("cora", display_name="Cora 7")
        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "sess-1.json").write_text(json.dumps({
            "session_id": "sess-1",
            "agent_name": "cora",
            "team_name": "my-team",
        }))

        service = _service(
            mock_client,
            sessions_dir=sessions_dir,
            environ={"CLAUDE_SESSION_ID": "sess-1"},
        )
        result = await service.set_presence("available")

        assert "Now Available" in result
        assert "Wake-from-idle: enabled" in result
        sent = json.loads(mock_client._ws.send.call_args[0][0])
        assert sent["users"][0]["presence"] == "available"

    @pytest.mark.asyncio
    async def test_available_includes_display_names(self, mock_client, tmp_path, monkeypatch):
        import voice_mode.connect.users as users_mod

        monkeypatch.setattr(users_mod, "CLAUDE_TEAMS_DIR", tmp_path / ".claude" / "teams")
        (users_mod.CLAUDE_TEAMS_DIR / "my-team" / "inboxes").mkdir(parents=True)
        mock_client.user_manager.add("cora", display_name="Cora 7")
        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "sess-1.json").write_text(json.dumps({
            "agent_name": "cora",
            "team_name": "my-team",
        }))

        result = await _service(
            mock_client,
            sessions_dir=sessions_dir,
            environ={"CLAUDE_SESSION_ID": "sess-1"},
        ).set_presence("available")

        assert "Cora 7" in result


class TestSetPresenceStaleSymlink:
    @pytest.mark.asyncio
    async def test_downgrades_without_removing_others_symlink(self, mock_client, tmp_path):
        user = mock_client.user_manager.add("cora")
        symlink = mock_client.user_manager.inbox_live_path(user.name)
        symlink.symlink_to(tmp_path / "other-sessions-target")

        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "sess-1.json").write_text(json.dumps({"agent_name": "cora"}))

        result = await _service(
            mock_client,
            sessions_dir=sessions_dir,
            environ={"CLAUDE_SESSION_ID": "sess-1"},
        ).set_presence("available")

        assert "Set to Away" in result
        assert "TeamCreate" in result
        assert symlink.is_symlink(), "Should not remove another session's symlink"

    @pytest.mark.asyncio
    async def test_stale_symlink_replaced_with_correct_team(self, mock_client, tmp_path, monkeypatch):
        import voice_mode.connect.users as users_mod

        monkeypatch.setattr(users_mod, "CLAUDE_TEAMS_DIR", tmp_path / ".claude" / "teams")
        correct_inbox = users_mod.CLAUDE_TEAMS_DIR / "correct-team" / "inboxes" / "team-lead.json"
        correct_inbox.parent.mkdir(parents=True)

        user = mock_client.user_manager.add("cora")
        symlink = mock_client.user_manager.inbox_live_path(user.name)
        wrong_inbox = users_mod.CLAUDE_TEAMS_DIR / "wrong-team" / "inboxes" / "team-lead.json"
        symlink.symlink_to(wrong_inbox)

        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "sess-1.json").write_text(json.dumps({
            "agent_name": "cora",
            "team_name": "correct-team",
        }))

        result = await _service(
            mock_client,
            sessions_dir=sessions_dir,
            environ={"CLAUDE_SESSION_ID": "sess-1"},
        ).set_presence("available")

        assert "Now Available" in result
        assert symlink.is_symlink()
        assert symlink.readlink() == correct_inbox


class TestSetPresenceAway:
    @pytest.mark.asyncio
    async def test_away_sends_online_wire_presence(self, mock_client):
        mock_client.user_manager.add("cora")

        result = await _service(mock_client).set_presence("away")

        sent = json.loads(mock_client._ws.send.call_args[0][0])
        assert sent["users"][0]["presence"] == "online"
        assert "Now Away" in result

    @pytest.mark.asyncio
    async def test_away_does_not_check_subscription(self, mock_client):
        mock_client.user_manager.add("cora")
        mock_client.user_manager.is_subscribed = MagicMock()

        result = await _service(mock_client).set_presence("away")

        mock_client.user_manager.is_subscribed.assert_not_called()
        assert "Now Away" in result


class TestSetPresenceWebSocketError:
    @pytest.mark.asyncio
    async def test_ws_send_failure(self, mock_client):
        mock_client.user_manager.add("cora")
        mock_client.send_presence_update.side_effect = Exception("Connection lost")

        result = await _service(mock_client).set_presence("available")

        assert "Failed to set presence" in result
        assert "Connection lost" in result


class TestGetSessionData:
    def test_direct_lookup_via_env_var(self, tmp_path):
        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        session_data = {
            "session_id": "test-123",
            "agent_name": "wimo",
            "team_name": "wimo-voice",
        }
        (sessions_dir / "test-123.json").write_text(json.dumps(session_data))

        identity = ConnectSessionIdentity(
            sessions_dir=sessions_dir,
            environ={"CLAUDE_SESSION_ID": "test-123"},
        )
        result = identity.read()

        assert result["session_id"] == "test-123"
        assert result["team_name"] == "wimo-voice"

    def test_fallback_scan_by_agent_name(self, tmp_path):
        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)

        for i, (agent, team) in enumerate((('wimo', 'wimo-voice'), ('cora', 'cora-team'))):
            data = {"session_id": f"sess-{i}", "agent_name": agent, "team_name": team}
            (sessions_dir / f"sess-{i}.json").write_text(json.dumps(data))

        result = ConnectSessionIdentity(sessions_dir=sessions_dir, environ={}).read(
            agent_name="wimo"
        )

        assert result["agent_name"] == "wimo"
        assert result["team_name"] == "wimo-voice"

    def test_fallback_returns_empty_without_agent_name(self, tmp_path):
        result = ConnectSessionIdentity(
            sessions_dir=tmp_path / ".voicemode" / "sessions",
            environ={},
        ).read()

        assert result == {}

    def test_fallback_no_matching_agent(self, tmp_path):
        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "sess-1.json").write_text(json.dumps({
            "session_id": "sess-1",
            "agent_name": "cora",
            "team_name": "cora",
        }))

        result = ConnectSessionIdentity(sessions_dir=sessions_dir, environ={}).read(
            agent_name="wimo"
        )

        assert result == {}

    def test_compatibility_helper_uses_default_identity(self, tmp_path):
        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "test-123.json").write_text(json.dumps({"session_id": "test-123"}))

        with (
            patch.dict("os.environ", {"CLAUDE_SESSION_ID": "test-123"}),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            assert _get_session_data()["session_id"] == "test-123"


class TestSetPresenceMultipleUsers:
    @pytest.mark.asyncio
    async def test_multiple_users_all_included(self, mock_client, tmp_path, monkeypatch):
        import voice_mode.connect.users as users_mod

        monkeypatch.setattr(users_mod, "CLAUDE_TEAMS_DIR", tmp_path / ".claude" / "teams")
        (users_mod.CLAUDE_TEAMS_DIR / "my-team" / "inboxes").mkdir(parents=True)
        mock_client.user_manager.add("cora", display_name="Cora 7")
        mock_client.user_manager.add("echo", display_name="Echo")

        sessions_dir = tmp_path / ".voicemode" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "sess-1.json").write_text(json.dumps({
            "agent_name": "cora",
            "team_name": "my-team",
        }))

        result = await _service(
            mock_client,
            sessions_dir=sessions_dir,
            environ={"CLAUDE_SESSION_ID": "sess-1"},
        ).set_presence("available")

        sent = json.loads(mock_client._ws.send.call_args[0][0])
        assert len(sent["users"]) == 2
        assert {u["name"] for u in sent["users"]} == {"cora", "echo"}
        assert "Cora 7" in result
        assert "Echo" in result
