"""Tests for ElevenLabs TTS integration (voice_mode/elevenlabs_tts_stt.py)."""
import asyncio
import pytest
from unittest.mock import MagicMock, patch
import subprocess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(audio_bytes=b"\x00\x01\x02"):
    """Return a mock ElevenLabs client whose convert() yields audio bytes."""
    client = MagicMock()
    # Return fresh iterator each call (not exhausted after first call)
    client.text_to_speech.convert.side_effect = lambda **kwargs: iter([audio_bytes])
    return client


def _make_fake_proc(pid=1234, *, running_polls=0):
    """Return a fake ffplay process that exits after a bounded poll count."""
    proc = MagicMock()
    proc.pid = pid
    poll_values = [None] * running_polls + [0]
    proc.poll.side_effect = lambda: poll_values.pop(0) if poll_values else 0
    proc.wait.return_value = None
    return proc


def _tts_patches(mock_client):
    """
    Return the standard set of patches needed for elevenlabs_tts tests.

    VoiceSettings and play are imported *inside* the function body, so we
    patch them at their origin modules (elevenlabs.VoiceSettings, elevenlabs.play.play)
    rather than on voice_mode.elevenlabs_tts_stt.
    """
    return (
        patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
        patch("subprocess.run"),
        patch("elevenlabs.VoiceSettings", MagicMock),
    )


# ---------------------------------------------------------------------------
# Basic TTS
# ---------------------------------------------------------------------------

class TestElevenLabsTTSBasic:
    """Basic TTS call paths."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "test-voice-id")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "test-key")
    async def test_basic_tts_success(self):
        """Short text produces a single convert() call and returns success."""
        mock_client = _make_mock_client()

        with _tts_patches(mock_client)[0], _tts_patches(mock_client)[1], _tts_patches(mock_client)[2]:
            # Re-create patches so they share the same mock_client
            pass

        # Use explicit patches to share the same mock_client
        mock_client = _make_mock_client()
        p1 = patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client)
        p2 = patch("subprocess.run")
        p3 = patch("elevenlabs.VoiceSettings", MagicMock)

        with p1, p2, p3:
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, metrics, config = await elevenlabs_tts(
                text="Hello world",
                voice="caller-voice",
                model="caller-model",
            )

        assert success is True
        assert metrics is not None
        assert "generation" in metrics
        assert "playback" in metrics
        assert config["provider"] == "elevenlabs"
        # Caller params override config defaults
        assert config["voice"] == "caller-voice"
        assert config["model"] == "caller-model"

        # Only one chunk → one convert call, one play call
        mock_client.text_to_speech.convert.assert_called_once()
        # ffplay subprocess called in thread — verified by success=True

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "test-voice-id")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "test-key")
    async def test_tts_empty_text(self):
        """Empty string still calls convert() (edge-case, not an error)."""
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, metrics, config = await elevenlabs_tts(
                text="", voice="v", model="m",
            )

        assert success is True
        mock_client.text_to_speech.convert.assert_called_once()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "voice-id")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "key")
    async def test_tts_uses_caller_params_over_config(self):
        """convert() must use caller-provided voice/model, falling back to config."""
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            await elevenlabs_tts(text="hi", voice="caller-voice", model="caller-model")

        call_kwargs = mock_client.text_to_speech.convert.call_args
        assert call_kwargs.kwargs["voice_id"] == "caller-voice"
        assert call_kwargs.kwargs["model_id"] == "caller-model"


# ---------------------------------------------------------------------------
# Speed parameter
# ---------------------------------------------------------------------------

class TestElevenLabsTTSSpeed:
    """Speed parameter handling."""

    @pytest.mark.parametrize("speed", [0.7, 1.0, 1.2])
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_speed_values(self, speed):
        """Speed kwarg is forwarded to VoiceSettings."""
        mock_client = _make_mock_client()
        captured_settings = []

        class FakeVoiceSettings:
            def __init__(self, **kw):
                captured_settings.append(kw)

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", FakeVoiceSettings),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, _, _ = await elevenlabs_tts(
                text="test", voice="v", model="m", speed=speed,
            )

        assert success is True
        assert captured_settings[0]["speed"] == speed

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_forwards_elevenlabs_voice_profile(self, monkeypatch):
        """Voice profile settings are forwarded to ElevenLabs for consistent v3 delivery."""
        mock_client = _make_mock_client()
        captured_settings = []

        class FakeVoiceSettings:
            def __init__(self, **kw):
                captured_settings.append(kw)

        from voice_mode.runtime_context import RuntimeContext

        runtime = RuntimeContext.load(
            environment={
                "VOICEMODE_ELEVENLABS_VOICE_STABILITY": "0.74",
                "VOICEMODE_ELEVENLABS_VOICE_SIMILARITY_BOOST": "0.91",
                "VOICEMODE_ELEVENLABS_VOICE_STYLE": "0.33",
                "VOICEMODE_ELEVENLABS_VOICE_USE_SPEAKER_BOOST": "false",
                "VOICEMODE_ELEVENLABS_VOICE_SEED": "12345",
            }
        )
        monkeypatch.setattr("voice_mode.runtime_context.get_runtime_context", lambda: runtime)

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.Popen", return_value=_make_fake_proc()),
            patch("elevenlabs.VoiceSettings", FakeVoiceSettings),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            await elevenlabs_tts(text="test", voice="v", model="m")

        assert captured_settings[0] == {
            "speed": 1.2,
            "stability": 0.74,
            "similarity_boost": 0.91,
            "style": 0.33,
            "use_speaker_boost": False,
        }
        assert mock_client.text_to_speech.convert.call_args.kwargs["seed"] == 12345

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_default_speed_is_1_2(self):
        """When no speed kwarg is provided, default to 1.2."""
        mock_client = _make_mock_client()
        captured_settings = []

        class FakeVoiceSettings:
            def __init__(self, **kw):
                captured_settings.append(kw)

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", FakeVoiceSettings),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            await elevenlabs_tts(text="test", voice="v", model="m")

        assert captured_settings[0]["speed"] == 1.2


# ---------------------------------------------------------------------------
# Chunking for long text
# ---------------------------------------------------------------------------

class TestElevenLabsTTSChunking:
    """Text chunking for long inputs (>2000 chars)."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_long_text_is_chunked(self):
        """Text longer than 2000 chars is split into multiple convert() calls."""
        # Build a ~3000-char string of sentences
        sentences = []
        while sum(len(s) for s in sentences) < 3000:
            sentences.append("This is a moderately long sentence that will help us exceed the limit. ")
        long_text = " ".join(sentences)
        assert len(long_text) > 2000

        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, _, _ = await elevenlabs_tts(
                text=long_text, voice="v", model="m",
            )

        assert success is True
        assert mock_client.text_to_speech.convert.call_count >= 2
        # Verified by success=True and convert call count

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_does_not_create_provider_level_ducker(self):
        """Ducking is owned by ConverseSession, not the ElevenLabs provider."""
        mock_client = _make_mock_client()
        fake_proc = _make_fake_proc()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.Popen", return_value=fake_proc),
            patch("elevenlabs.VoiceSettings", MagicMock),
            patch("voice_mode.audio_ducker.DJDucker") as mock_ducker,
        ):
            fake_proc.poll.return_value = 0
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, _, _ = await elevenlabs_tts(text="hello", voice="v", model="m")

        assert success is True
        mock_ducker.assert_not_called()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_short_text_not_chunked(self):
        """Text under 2000 chars is NOT split."""
        short_text = "Hello. World. Foo bar."
        assert len(short_text) < 2000

        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, _, _ = await elevenlabs_tts(
                text=short_text, voice="v", model="m",
            )

        assert success is True
        mock_client.text_to_speech.convert.assert_called_once()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_chunking_splits_on_sentence_boundaries(self):
        """Chunks should end at sentence boundaries (.!?), not mid-sentence."""
        # 10 sentences of ~250 chars each → ~2500 total → 2 chunks
        sentence = "A" * 245 + ". "
        long_text = sentence * 10
        assert len(long_text) > 2000

        mock_client = _make_mock_client()
        recorded_chunks = []

        def capture_convert(**kwargs):
            recorded_chunks.append(kwargs["text"])
            return iter([b"\x00"])

        mock_client.text_to_speech.convert.side_effect = capture_convert

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            await elevenlabs_tts(text=long_text, voice="v", model="m")

        assert len(recorded_chunks) >= 2
        # Each chunk (except possibly the last) should end at a sentence boundary
        for chunk in recorded_chunks[:-1]:
            assert chunk.rstrip().endswith("."), f"Chunk does not end at sentence boundary: ...{chunk[-30:]}"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestElevenLabsTTSErrors:
    """Failure scenarios."""

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_api_error(self):
        """API error returns (False, None, error_config)."""
        mock_client = MagicMock()
        mock_client.text_to_speech.convert.side_effect = RuntimeError("API rate limit")

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, metrics, config = await elevenlabs_tts(
                text="hello", voice="v", model="m",
            )

        assert success is False
        assert metrics is None
        assert config["error_type"] == "all_providers_failed"
        assert "failed" in config["attempted_endpoints"][0]["error"].lower()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_network_error(self):
        """Network-level error is reported properly."""
        mock_client = MagicMock()
        mock_client.text_to_speech.convert.side_effect = ConnectionError("DNS resolution failed")

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.run"),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts 

            success, metrics, config = await elevenlabs_tts(
                text="hello", voice="v", model="m",
            )

        assert success is False
        assert "failed" in config["attempted_endpoints"][0]["error"].lower()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_tts_play_error_is_caught(self):
        """If subprocess.run (ffplay) raises, TTS reports failure."""
        mock_client = _make_mock_client()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.Popen", side_effect=OSError("ffplay not found")),
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            success, metrics, config = await elevenlabs_tts(
                text="hello", voice="v", model="m",
            )

        assert success is False
        assert "failed" in config["attempted_endpoints"][0]["error"].lower()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_cancelled_tts_stops_active_playback(self):
        """Cancellation should terminate the active ffplay process."""
        mock_client = _make_mock_client()

        fake_proc = _make_fake_proc(pid=1234)
        active_proc = MagicMock()
        active_proc.pid = 1234
        active_proc.poll.return_value = None
        active_proc.wait.return_value = None

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.Popen", return_value=fake_proc),
            patch("elevenlabs.VoiceSettings", MagicMock),
            patch("os.killpg") as mock_killpg,
        ):
            from voice_mode.elevenlabs_tts_stt import elevenlabs_tts

            from voice_mode.elevenlabs_tts_stt import stop_current_playback, _current_playback_process

            await elevenlabs_tts(text="hello", voice="v", model="m")
            assert _current_playback_process is None

            # Simulate an active playback that must be stopped on disconnect.
            import voice_mode.elevenlabs_tts_stt as mod
            mod._current_playback_process = active_proc
            stop_current_playback()

        mock_killpg.assert_called_once_with(1234, subprocess.signal.SIGTERM)

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stop_current_playback_cancels_before_ffplay_exists(self):
        """A stop request during audio generation should cancel before playback starts."""
        import voice_mode.elevenlabs_tts_stt as mod

        class BlockingIterator:
            def __iter__(self):
                return self

            def __next__(self):
                mod.stop_current_playback()
                raise StopIteration

        mock_client = MagicMock()
        mock_client.text_to_speech.convert.return_value = BlockingIterator()

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.Popen") as mock_popen,
            patch("elevenlabs.VoiceSettings", MagicMock),
        ):
            with pytest.raises(asyncio.CancelledError):
                await mod.elevenlabs_tts(text="hello", voice="v", model="m")

        mock_popen.assert_not_called()

    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_MODEL", "eleven_v3")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_TTS_VOICE", "v")
    @patch("voice_mode.elevenlabs_tts_stt.ELEVENLABS_API_KEY", "k")
    async def test_stop_current_playback_aborts_running_tts_thread(self):
        """A stop request while ffplay runs should make elevenlabs_tts cancel promptly."""
        mock_client = _make_mock_client()

        fake_proc = _make_fake_proc(pid=2345, running_polls=5)

        def fake_wait(timeout=None):
            if timeout == 0.1:
                mod.stop_current_playback()
                raise subprocess.TimeoutExpired(cmd="ffplay", timeout=0.1)
            return None

        fake_proc.wait.side_effect = fake_wait

        import voice_mode.elevenlabs_tts_stt as mod

        with (
            patch("voice_mode.elevenlabs_client.get_client", return_value=mock_client),
            patch("subprocess.Popen", return_value=fake_proc),
            patch("elevenlabs.VoiceSettings", MagicMock),
            patch("os.killpg") as mock_killpg,
        ):
            with pytest.raises(asyncio.CancelledError):
                await mod.elevenlabs_tts(text="hello", voice="v", model="m")

        assert mock_killpg.called



# ---------------------------------------------------------------------------
# SpeechService boundary
# ---------------------------------------------------------------------------

class TestSpeechServiceSpeakBoundary:
    """Provider selection and compatibility are hidden behind SpeechService."""

    async def test_speak_selects_endpoint_voice_and_model(self):
        from voice_mode.provider_discovery import EndpointInfo
        from voice_mode.voice_provider import SpeakOptions, SpeechService

        class FakeRegistry:
            def __init__(self):
                self.initialized = False
                self.endpoint = EndpointInfo(
                    base_url="elevenlabs://tts",
                    models=["eleven_v3"],
                    voices=["voice-a"],
                    provider_type="elevenlabs",
                )

            async def initialize(self):
                self.initialized = True

            def find_endpoint_with_voice(self, voice):
                return self.endpoint if voice == "voice-a" else None

            def find_endpoint_with_model(self, service_type, model):
                return self.endpoint if service_type == "tts" and model == "eleven_v3" else None

            def get_endpoints(self, service_type):
                return [self.endpoint] if service_type == "tts" else []

        class FakeProvider:
            def __init__(self):
                self.tts_kwargs = None

            async def tts(self, **kwargs):
                self.tts_kwargs = kwargs
                return True, {"generation": 1}, {"provider": "elevenlabs"}

        registry = FakeRegistry()
        provider = FakeProvider()
        service = SpeechService(provider=provider, registry=registry)

        success, metrics, config = await service.speak(SpeakOptions(text="hello"))

        assert registry.initialized is True
        assert success is True
        assert metrics == {"generation": 1}
        assert config == {"provider": "elevenlabs"}
        assert provider.tts_kwargs["text"] == "hello"
        assert provider.tts_kwargs["voice"] == "voice-a"
        assert provider.tts_kwargs["model"] == "eleven_v3"
        assert provider.tts_kwargs["base_url"] == "elevenlabs://tts"

    async def test_tts_orchestrator_delegates_to_speech_service(self):
        from voice_mode.tts_orchestrator import TTSOrchestrator, TTSRequest

        class FakeSpeechService:
            def __init__(self):
                self.options = None

            async def speak(self, options):
                self.options = options
                return True, {"playback": 2}, {"provider": "elevenlabs"}

        service = FakeSpeechService()
        orchestrator = TTSOrchestrator(speech_service=service)

        success, metrics = await orchestrator.speak(
            TTSRequest(
                text="hello",
                voice="voice-b",
                model="eleven_v3",
                base_url="elevenlabs://tts",
                speed=1.1,
            )
        )

        assert success is True
        assert metrics == {"playback": 2}
        assert service.options.text == "hello"
        assert service.options.voice == "voice-b"
        assert service.options.model == "eleven_v3"
        assert service.options.speed == 1.1


class TestProviderCompatibilityBoundary:
    """Legacy providers.py functions are backed by the registry boundary."""

    async def test_get_tts_client_and_voice_returns_selected_endpoint(self):
        from voice_mode.provider_discovery import EndpointInfo
        import voice_mode.providers as providers

        endpoint = EndpointInfo(
            base_url="elevenlabs://tts",
            models=["eleven_v3"],
            voices=["voice-a"],
            provider_type="elevenlabs",
        )

        class FakeRegistry:
            async def initialize(self):
                pass

            def select_tts_endpoint(self, *, voice=None, model=None, base_url=None):
                assert voice == "voice-a"
                assert model is None
                assert base_url is None
                return endpoint

        class FakeProvider:
            pass

        with (
            patch.object(providers, "provider_registry", FakeRegistry()),
            patch.object(providers, "get_voice_provider", return_value=FakeProvider()) as get_provider,
        ):
            provider, voice, model, selected_endpoint = await providers.get_tts_client_and_voice(voice="voice-a")

        assert isinstance(provider, FakeProvider)
        assert voice == "voice-a"
        assert model == "eleven_v3"
        assert selected_endpoint is endpoint
        get_provider.assert_called_once()

    async def test_provider_discovery_selects_configured_tts_endpoint(self):
        from voice_mode.provider_discovery import ProviderRegistry

        registry = ProviderRegistry()
        await registry.initialize()

        endpoint = registry.select_tts_endpoint(model="eleven_v3")

        assert endpoint is not None
        assert endpoint.provider_type == "elevenlabs"
        assert "eleven_v3" in endpoint.models
