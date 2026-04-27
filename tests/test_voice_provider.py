from unittest.mock import AsyncMock

import pytest

from voice_mode.provider_discovery import EndpointInfo
from voice_mode.voice_provider import (
    DEFAULT_BATCH_STT_MODEL,
    DEFAULT_REALTIME_STT_MODEL,
    ListenOptions,
    SpeechService,
)


class FakeSTTRegistry:
    def __init__(self):
        self.initialized = False
        self.endpoint = EndpointInfo(
            base_url="elevenlabs://stt",
            models=[DEFAULT_BATCH_STT_MODEL, DEFAULT_REALTIME_STT_MODEL],
            voices=[],
            provider_type="elevenlabs",
        )

    async def initialize(self):
        self.initialized = True

    def find_endpoint_with_model(self, service_type, model):
        if service_type == "stt" and model in self.endpoint.models:
            return self.endpoint
        return None

    def get_endpoints(self, service_type):
        return [self.endpoint] if service_type == "stt" else []


@pytest.mark.asyncio
async def test_speech_service_listen_batch_is_provider_passthrough():
    audio_file = object()
    provider = type(
        "FakeProvider",
        (),
        {
            "batch_stt": AsyncMock(return_value={"text": "batch"}),
            "realtime_stt": AsyncMock(return_value={"text": "unused"}),
        },
    )()
    registry = FakeSTTRegistry()
    service = SpeechService(provider=provider, registry=registry)

    result = await service.listen(ListenOptions(audio_file=audio_file, model="scribe_v2"))

    assert registry.initialized is True
    assert result == {"text": "batch"}
    provider.batch_stt.assert_awaited_once_with(
        audio_file=audio_file,
        model="scribe_v2",
        base_url="elevenlabs://stt",
    )
    provider.realtime_stt.assert_not_awaited()


@pytest.mark.asyncio
async def test_speech_service_listen_realtime_does_not_retry_fallback_or_normalize():
    provider_result = {"error_type": "connection_failed", "provider": "elevenlabs"}
    provider = type(
        "FakeProvider",
        (),
        {
            "batch_stt": AsyncMock(return_value={"text": "fallback should not run"}),
            "realtime_stt": AsyncMock(return_value=provider_result),
        },
    )()
    registry = FakeSTTRegistry()
    service = SpeechService(provider=provider, registry=registry)

    def on_partial(text):
        return None

    result = await service.listen(
        ListenOptions(
            max_duration=5.0,
            min_duration=1.5,
            language_code="en",
            vad_aggressiveness=2,
            disable_silence_detection=True,
            previous_text="previous turn",
            on_partial=on_partial,
        )
    )

    assert result is provider_result
    provider.realtime_stt.assert_awaited_once_with(
        max_duration=5.0,
        min_duration=1.5,
        model=DEFAULT_REALTIME_STT_MODEL,
        base_url="elevenlabs://stt",
        language_code="en",
        vad_aggressiveness=2,
        disable_silence_detection=True,
        previous_text="previous turn",
        on_partial=on_partial,
    )
    provider.batch_stt.assert_not_awaited()
