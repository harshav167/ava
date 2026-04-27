"""Tests for Exchanges models and MCP tool exposure."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from voice_mode.exchanges.models import Exchange, ExchangeMetadata
from voice_mode.exchanges.writer import ExchangeWriter


def _exchange_from_dict(entry: dict) -> Exchange:
    return Exchange(
        version=entry.get("version", 1),
        timestamp=datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")),
        conversation_id=entry["conversation_id"],
        type=entry["type"],
        text=entry["text"],
        project_path=entry.get("project_path"),
        audio_file=entry.get("audio_file"),
        duration_ms=entry.get("duration_ms"),
        metadata=ExchangeMetadata.from_dict(entry.get("metadata", {}))
        if entry.get("metadata")
        else None,
    )


def _write_exchange_log(base_dir: Path, entries: list[dict]) -> None:
    writer = ExchangeWriter(logs_dir=base_dir / "logs" / "conversations")
    for entry in entries:
        writer.append(_exchange_from_dict(entry))


@pytest.fixture
def sample_exchanges_dir(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    entries = [
        {
            "version": 3,
            "timestamp": now.isoformat(),
            "conversation_id": "conv_1",
            "type": "stt",
            "text": "search for websocket bugs",
            "project_path": "/tmp/project",
            "metadata": {
                "voice_mode_version": "8.5.1",
                "provider": "elevenlabs",
                "model": "scribe_v2_realtime",
                "transport": "local",
                "timing": "record 1.0s, stt 0.2s",
                "is_fallback": True,
                "fallback_reason": "primary unavailable",
            },
        },
        {
            "version": 3,
            "timestamp": (now + timedelta(seconds=2)).isoformat(),
            "conversation_id": "conv_1",
            "type": "tts",
            "text": "I found two websocket issues.",
            "project_path": "/tmp/project",
            "metadata": {
                "voice_mode_version": "8.5.1",
                "provider": "elevenlabs",
                "model": "eleven_v3",
                "voice": "nova",
                "transport": "local",
                "timing": "ttfa 0.1s, gen 0.4s, play 0.8s",
            },
        },
        {
            "version": 3,
            "timestamp": (now + timedelta(days=-1)).isoformat(),
            "conversation_id": "conv_2",
            "type": "stt",
            "text": "play ambient focus music",
            "project_path": "/tmp/project",
            "metadata": {
                "voice_mode_version": "8.5.1",
                "provider": "elevenlabs",
                "model": "scribe_v2_realtime",
                "transport": "livekit",
                "error": "timeout",
            },
        },
    ]

    _write_exchange_log(tmp_path, entries)

    from voice_mode.exchanges.reader import ExchangeReader as RealReader

    monkeypatch.setattr(
        "voice_mode.tools.exchanges.ExchangeReader",
        lambda: RealReader(base_dir=tmp_path),
    )
    return tmp_path


class TestExchangeMetadata:
    def test_round_trip_preserves_fallback_fields(self):
        metadata = ExchangeMetadata(
            voice_mode_version="8.5.1",
            provider="elevenlabs",
            is_fallback=True,
            fallback_reason="primary unavailable",
        )
        exchange = Exchange(
            version=3,
            timestamp=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
            conversation_id="conv_1",
            type="stt",
            text="hello",
            metadata=metadata,
        )

        restored = Exchange.from_jsonl(exchange.to_jsonl())

        assert restored.metadata is not None
        assert restored.metadata.is_fallback is True
        assert restored.metadata.fallback_reason == "primary unavailable"

    def test_round_trip_preserves_unknown_metadata_fields(self):
        metadata = ExchangeMetadata.from_dict(
            {
                "voice_mode_version": "8.5.1",
                "provider": "elevenlabs",
                "custom_metric": "preserved",
            }
        )
        exchange = Exchange(
            version=3,
            timestamp=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
            conversation_id="conv_1",
            type="tts",
            text="hello",
            metadata=metadata,
        )

        restored = Exchange.from_jsonl(exchange.to_jsonl())

        assert restored.metadata is not None
        assert restored.metadata.to_dict()["custom_metric"] == "preserved"


class TestExchangeReader:
    def test_reader_skips_malformed_lines_and_keeps_valid_records(self, tmp_path, caplog):
        from voice_mode.exchanges.reader import ExchangeReader

        logs_dir = tmp_path / "logs" / "conversations"
        writer = ExchangeWriter(logs_dir=logs_dir)
        writer.append(
            Exchange(
                version=3,
                timestamp=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
                conversation_id="conv_valid",
                type="stt",
                text="valid before malformed",
            )
        )
        log_path = next(logs_dir.glob("exchanges_*.jsonl"))
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
            handle.write("\n")
            handle.write(
                Exchange(
                    version=3,
                    timestamp=datetime(2026, 3, 26, 12, 1, tzinfo=timezone.utc),
                    conversation_id="conv_valid",
                    type="tts",
                    text="valid after malformed",
                ).to_jsonl()
                + "\n"
            )

        exchanges = list(ExchangeReader(logs_dir=logs_dir).read_all())

        assert [exchange.text for exchange in exchanges] == [
            "valid before malformed",
            "valid after malformed",
        ]
        assert "Failed to parse line" in caplog.text

    def test_reader_accepts_legacy_records_without_version_or_metadata(self, tmp_path):
        from voice_mode.exchanges.reader import ExchangeReader

        logs_dir = tmp_path / "logs" / "conversations"
        logs_dir.mkdir(parents=True)
        log_path = logs_dir / "exchanges_2026-03-26.jsonl"
        legacy_record = {
            "timestamp": "2026-03-26T12:00:00Z",
            "conversation_id": "conv_legacy",
            "type": "conversation",
            "text": "legacy assistant message",
            "project_path": "/tmp/project",
            "audio_file": "legacy.wav",
        }
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(legacy_record) + "\n")

        exchanges = list(ExchangeReader(logs_dir=logs_dir).read_all())

        assert len(exchanges) == 1
        assert exchanges[0].version == 1
        assert exchanges[0].type == "tts"
        assert exchanges[0].text == "legacy assistant message"
        assert exchanges[0].audio_file == "legacy.wav"


def test_conversation_logger_output_reads_through_exchange_reader(tmp_path):
    from voice_mode.conversation_logger import ConversationLogger
    from voice_mode.exchanges.reader import ExchangeReader

    logs_dir = tmp_path / "logs" / "conversations"
    logger = ConversationLogger(base_dir=logs_dir)
    logger.conversation_id = "conv_contract"
    logger.current_project_path = str(tmp_path / "project")

    logger.log_stt(
        "hello from the user",
        audio_file="stt.wav",
        duration_ms=1200,
        provider="elevenlabs",
        model="scribe_v2_realtime",
        transport="local",
        language="en",
    )
    logger.log_tts(
        "hello from the assistant",
        audio_file="tts.wav",
        duration_ms=900,
        provider="elevenlabs",
        model="eleven_v3",
        voice="nova",
        transport="local",
    )

    log_files = list(logs_dir.glob("exchanges_*.jsonl"))
    assert len(log_files) == 1
    assert log_files[0].name.startswith("exchanges_")
    assert log_files[0].name.endswith(".jsonl")

    exchanges = ExchangeReader(base_dir=tmp_path).read_conversation("conv_contract")

    assert len(exchanges) == 2
    assert exchanges[0].type == "stt"
    assert exchanges[0].text == "hello from the user"
    assert exchanges[0].audio_file == "stt.wav"
    assert exchanges[0].duration_ms == 1200
    assert exchanges[0].metadata is not None
    assert exchanges[0].metadata.provider == "elevenlabs"
    assert exchanges[0].metadata.language == "en"
    assert exchanges[1].type == "tts"
    assert exchanges[1].metadata is not None
    assert exchanges[1].metadata.voice == "nova"


class TestExchangesTool:
    @pytest.mark.asyncio
    async def test_view_returns_recent_exchanges(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="view", limit=2, format="simple")

        assert "websocket" in result
        assert "I found two websocket issues." in result

    @pytest.mark.asyncio
    async def test_search_filters_by_text(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(
            action="search", query="ambient", days=7, format="json"
        )
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["text"] == "play ambient focus music"

    @pytest.mark.asyncio
    async def test_search_can_return_full_conversation(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(
            action="search",
            query="websocket",
            days=7,
            show_conversation=True,
            format="markdown",
            limit=5,
        )

        assert "# Conversation conv_1" in result
        assert "search for websocket bugs" in result
        assert "I found two websocket issues." in result

    @pytest.mark.asyncio
    async def test_stats_summary_works(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="stats", days=7, stats_view="summary")

        assert "Exchange Statistics Summary" in result
        assert "Total Exchanges: 3" in result

    @pytest.mark.asyncio
    async def test_stats_providers_json(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="stats", days=7, stats_view="providers")
        data = json.loads(result)

        assert data["providers"]["elevenlabs"] == 3
        assert "models" in data
        assert "voices" in data

    @pytest.mark.asyncio
    async def test_export_csv_returns_header_and_rows(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="export", days=7, format="csv", limit=10)

        assert result.splitlines()[0].startswith("timestamp,conversation_id,type,text")
        assert "search for websocket bugs" in result

    @pytest.mark.asyncio
    async def test_export_html_requires_single_conversation(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="export", days=7, format="html")

        assert "single conversation" in result

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="view", date="03-26-2026")

        assert "YYYY-MM-DD" in result

    @pytest.mark.asyncio
    async def test_search_requires_query(self, sample_exchanges_dir):
        from voice_mode.tools.exchanges import exchanges

        result = await exchanges(action="search")

        assert "query is required" in result
