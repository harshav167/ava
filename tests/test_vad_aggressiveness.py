"""Tests for VAD aggressiveness parameter in voice_mode."""

import pytest
from unittest.mock import patch, MagicMock
import sys

# Mock webrtcvad before importing voice_mode modules
sys.modules['webrtcvad'] = MagicMock()

from voice_mode.tools.converse import (  # noqa: E402
    record_audio_with_silence_detection
)
from voice_mode.config import (  # noqa: E402
    VAD_AGGRESSIVENESS
)
from voice_mode.silero_vad import get_threshold_for_aggressiveness  # noqa: E402


class TestVADAggressiveness:
    """Test VAD aggressiveness parameter functionality."""

    @pytest.fixture
    def mock_silero_vad(self):
        """Mock Silero VAD for testing."""
        mock_instance = MagicMock()
        mock_instance.return_value = 0.8  # Default: speech detected
        mock_instance.reset_states = MagicMock()
        with patch('voice_mode.tools.converse.get_silero_vad', return_value=mock_instance):
            with patch('voice_mode.tools.converse.SILERO_VAD_AVAILABLE', True):
                yield mock_instance

    @pytest.fixture
    def mock_webrtc_vad(self):
        """Mock webrtcvad.Vad class for WebRTC fallback testing."""
        with patch('voice_mode.tools.converse.webrtcvad') as mock_webrtcvad:
            mock_vad_instance = MagicMock()
            mock_vad_instance.is_speech.return_value = True
            mock_webrtcvad.Vad.return_value = mock_vad_instance
            yield mock_webrtcvad

    @pytest.fixture
    def mock_audio_recording(self):
        """Mock audio recording functions."""
        with patch('voice_mode.tools.converse.sd') as mock_sd:
            # Setup InputStream context manager
            mock_stream = MagicMock()
            mock_sd.InputStream.return_value.__enter__.return_value = mock_stream
            yield mock_sd

    def test_silero_threshold_mapping(self):
        """Test that aggressiveness maps to correct Silero thresholds."""
        assert get_threshold_for_aggressiveness(0) == 0.3
        assert get_threshold_for_aggressiveness(1) == 0.5
        assert get_threshold_for_aggressiveness(2) == 0.7
        assert get_threshold_for_aggressiveness(3) == 0.85
        # Unknown value should default to 0.5
        assert get_threshold_for_aggressiveness(99) == 0.5

    def test_silero_used_when_available(self, mock_silero_vad, mock_audio_recording):
        """Test that Silero VAD is preferred over WebRTC when available."""
        with patch('voice_mode.tools.converse.VAD_AVAILABLE', True):
            with patch('queue.Queue') as mock_queue:
                mock_queue_instance = MagicMock()
                mock_queue_instance.get.side_effect = Exception("Timeout")
                mock_queue.return_value = mock_queue_instance

                try:
                    record_audio_with_silence_detection(
                        max_duration=1.0,
                        vad_aggressiveness=2
                    )
                except Exception:
                    pass

        # Silero VAD should have been initialized (reset_states called)
        mock_silero_vad.reset_states.assert_called_once()

    def test_webrtc_fallback_when_silero_unavailable(self, mock_webrtc_vad, mock_audio_recording):
        """Test that WebRTC VAD is used when Silero is not available."""
        with patch('voice_mode.tools.converse.SILERO_VAD_AVAILABLE', False):
            with patch('voice_mode.tools.converse.WEBRTC_VAD_AVAILABLE', True):
                with patch('voice_mode.tools.converse.VAD_AVAILABLE', True):
                    with patch('queue.Queue') as mock_queue:
                        mock_queue_instance = MagicMock()
                        mock_queue_instance.get.side_effect = Exception("Timeout")
                        mock_queue.return_value = mock_queue_instance

                        try:
                            record_audio_with_silence_detection(
                                max_duration=1.0,
                                vad_aggressiveness=2
                            )
                        except Exception:
                            pass

        # WebRTC VAD should have been initialized with the aggressiveness level
        mock_webrtc_vad.Vad.assert_called_with(2)

    def test_webrtc_fallback_uses_default_aggressiveness(self, mock_webrtc_vad, mock_audio_recording):
        """Test that WebRTC fallback uses default aggressiveness when None."""
        with patch('voice_mode.tools.converse.SILERO_VAD_AVAILABLE', False):
            with patch('voice_mode.tools.converse.WEBRTC_VAD_AVAILABLE', True):
                with patch('voice_mode.tools.converse.VAD_AVAILABLE', True):
                    with patch('queue.Queue') as mock_queue:
                        mock_queue_instance = MagicMock()
                        mock_queue_instance.get.side_effect = Exception("Timeout")
                        mock_queue.return_value = mock_queue_instance

                        try:
                            record_audio_with_silence_detection(
                                max_duration=1.0,
                                vad_aggressiveness=None
                            )
                        except Exception:
                            pass

        # Should use the default VAD_AGGRESSIVENESS from config
        mock_webrtc_vad.Vad.assert_called_with(VAD_AGGRESSIVENESS)

    def test_silero_aggressiveness_parameter_override(self, mock_silero_vad, mock_audio_recording):
        """Test that vad_aggressiveness parameter maps to Silero thresholds."""
        with patch('voice_mode.tools.converse.VAD_AVAILABLE', True):
            with patch('voice_mode.tools.converse.get_threshold_for_aggressiveness') as mock_threshold:
                mock_threshold.return_value = 0.7

                with patch('queue.Queue') as mock_queue:
                    mock_queue_instance = MagicMock()
                    mock_queue_instance.get.side_effect = Exception("Timeout")
                    mock_queue.return_value = mock_queue_instance

                    try:
                        record_audio_with_silence_detection(
                            max_duration=1.0,
                            vad_aggressiveness=2
                        )
                    except Exception:
                        pass

                # Verify threshold was requested for aggressiveness level 2
                mock_threshold.assert_called_with(2)
