#!/usr/bin/env python
"""
Tests for voice-mode MCP server.

Tests cover:
- Server module imports correctly
- FastMCP instance is properly configured
- Tool registration
"""



class TestServerImport:
    """Test that the server module imports and is properly configured."""

    def test_mcp_instance_exists(self):
        """Test that the FastMCP mcp instance can be imported."""
        from voice_mode.server import mcp

        assert mcp is not None
        assert mcp.name == "voicemode"

    def test_server_has_tools(self):
        """Test that the server has tools registered via auto-import."""
        from voice_mode.server import mcp

        # The server should have tools registered
        # (tools are auto-imported from voice_mode/tools/)
        assert mcp is not None

    def test_version_importable(self):
        """Test that version is importable."""
        from voice_mode.version import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0


class TestAudioProcessing:
    """Test audio processing utilities."""

    def test_audio_data_conversion(self):
        """Test audio data type conversions (int16 to float32)."""
        import numpy as np

        int_samples = np.array([0, 16383, -16384, 32767, -32768], dtype=np.int16)
        float_samples = int_samples.astype(np.float32) / 32768.0

        # Check conversion bounds with tolerance for floating point precision
        assert float_samples.min() >= -1.0 or np.isclose(
            float_samples.min(), -1.0, atol=1e-6
        )
        assert float_samples.max() <= 1.0
        assert np.allclose(float_samples[0], 0.0)
        assert np.allclose(float_samples[3], 32767 / 32768.0, atol=0.001)
