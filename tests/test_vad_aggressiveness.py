"""Tests for VAD aggressiveness parameter in voice_mode."""

import pytest
import numpy as np
import asyncio
import queue
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import sys

# Mock webrtcvad before importing voice_mode modules
sys.modules['webrtcvad'] = MagicMock()

from voice_mode.tools.converse import (
    record_audio_with_silence_detection
)
from voice_mode.config import (
    SAMPLE_RATE,
    VAD_CHUNK_DURATION_MS,
    VAD_AGGRESSIVENESS
)


class TestVADAggressiveness:
    """Test VAD aggressiveness parameter functionality."""
    
    @pytest.fixture
    def mock_vad(self):
        """Mock webrtcvad.Vad class."""
        with patch('voice_mode.tools.converse.webrtcvad') as mock_webrtcvad:
            mock_vad_instance = MagicMock()
            mock_vad_instance.is_speech.return_value = True
            mock_webrtcvad.Vad.return_value = mock_vad_instance
            yield mock_webrtcvad
    
    @pytest.fixture
    def mock_audio_recording(self):
        """Mock audio recording functions."""
        with patch('voice_mode.tools.converse.sd') as mock_sd:
            # Create a simple audio chunk
            chunk = np.random.randint(-1000, 1000, 
                                    size=int(SAMPLE_RATE * VAD_CHUNK_DURATION_MS / 1000), 
                                    dtype=np.int16)
            
            # Setup InputStream context manager
            mock_stream = MagicMock()
            mock_sd.InputStream.return_value.__enter__.return_value = mock_stream
            
            yield mock_sd
    
    def test_vad_aggressiveness_parameter_override(self, mock_vad, mock_audio_recording):
        """Test that vad_aggressiveness parameter overrides the default."""
        # Test with different aggressiveness levels
        for aggressiveness in [0, 1, 2, 3]:
            # Reset the mock
            mock_vad.reset_mock()
            
            # Call with specific aggressiveness
            with patch('voice_mode.tools.converse.VAD_AVAILABLE', True):
                # We need to mock the audio queue behavior
                with patch('queue.Queue') as mock_queue:
                    # Make the queue return some data then timeout
                    mock_queue_instance = MagicMock()
                    mock_queue_instance.get.side_effect = [
                        np.zeros((480, 1), dtype=np.int16),  # One chunk
                        Exception("Timeout")  # Stop the loop
                    ]
                    mock_queue.return_value = mock_queue_instance
                    
                    try:
                        record_audio_with_silence_detection(
                            max_duration=1.0,
                            vad_aggressiveness=aggressiveness
                        )
                    except:
                        pass  # Expected due to our mock setup
            
            # Verify VAD was initialized with the correct aggressiveness
            mock_vad.Vad.assert_called_with(aggressiveness)
    
    def test_vad_aggressiveness_uses_default_when_none(self, mock_vad, mock_audio_recording):
        """Test that None vad_aggressiveness uses the default from config."""
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
                except:
                    pass
        
        # Should use the default VAD_AGGRESSIVENESS from config
        mock_vad.Vad.assert_called_with(VAD_AGGRESSIVENESS)
    
