"""Silero VAD wrapper using ONNX Runtime (no PyTorch dependency).

Provides a lightweight Voice Activity Detection interface using the Silero VAD
ONNX model. The model is downloaded on first use and cached locally.

The model expects 512 samples at 16kHz per chunk (32ms) and returns a
probability score between 0 and 1 indicating likelihood of speech.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Model download URL and cache location
_MODEL_URL = "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
_CACHE_DIR = Path.home() / ".voicemode" / "models"
_MODEL_PATH = _CACHE_DIR / "silero_vad.onnx"

# Silero VAD constants
SILERO_SAMPLE_RATE = 16000
SILERO_CHUNK_SAMPLES = 512  # 512 samples at 16kHz = 32ms per chunk
SILERO_CONTEXT_SIZE = 64    # Context window at 16kHz

# Aggressiveness-to-threshold mapping
# 0 = very tolerant (low threshold), 3 = very strict (high threshold)
AGGRESSIVENESS_THRESHOLDS = {
    0: 0.3,
    1: 0.5,
    2: 0.7,
    3: 0.85,
}


class SileroVAD:
    """Silero Voice Activity Detection using ONNX Runtime.

    Maintains internal state across calls for streaming audio processing.
    Call reset_states() between separate audio streams.
    """

    def __init__(self, model_path: Optional[str] = None):
        """Initialize the Silero VAD model.

        Args:
            model_path: Path to the ONNX model file. If None, uses the
                default cached location and downloads if needed.
        """
        import onnxruntime

        path = model_path or str(_ensure_model())

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1

        if "CPUExecutionProvider" in onnxruntime.get_available_providers():
            self.session = onnxruntime.InferenceSession(
                path, providers=["CPUExecutionProvider"], sess_options=opts
            )
        else:
            self.session = onnxruntime.InferenceSession(path, sess_options=opts)

        self.reset_states()
        logger.info("Silero VAD model loaded successfully (ONNX)")

    def reset_states(self, batch_size: int = 1) -> None:
        """Reset internal model state. Call between separate audio streams."""
        self._state = np.zeros((2, batch_size, 128), dtype=np.float32)
        self._context = np.zeros((batch_size, SILERO_CONTEXT_SIZE), dtype=np.float32)
        self._last_sr = 0
        self._last_batch_size = 0

    def __call__(self, audio: np.ndarray, sample_rate: int = SILERO_SAMPLE_RATE) -> float:
        """Run VAD on a single audio chunk and return speech probability.

        Args:
            audio: Audio samples as float32 or int16 numpy array.
                Must be exactly SILERO_CHUNK_SAMPLES (512) samples at 16kHz.
            sample_rate: Sample rate of the audio (must be 16000).

        Returns:
            Speech probability between 0.0 and 1.0.
        """
        if sample_rate != SILERO_SAMPLE_RATE:
            raise ValueError(
                f"Silero VAD requires {SILERO_SAMPLE_RATE}Hz audio, got {sample_rate}Hz"
            )

        # Convert int16 to float32 if needed
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Ensure correct shape: (1, num_samples)
        if audio.ndim == 1:
            audio = audio.reshape(1, -1)

        if audio.shape[-1] != SILERO_CHUNK_SAMPLES:
            raise ValueError(
                f"Expected {SILERO_CHUNK_SAMPLES} samples, got {audio.shape[-1]}"
            )

        batch_size = audio.shape[0]

        # Reset states if batch size or sample rate changed
        if not self._last_batch_size:
            self.reset_states(batch_size)
        if self._last_sr and self._last_sr != sample_rate:
            self.reset_states(batch_size)
        if self._last_batch_size and self._last_batch_size != batch_size:
            self.reset_states(batch_size)

        # Prepend context
        x = np.concatenate([self._context, audio], axis=1).astype(np.float32)

        # Run inference
        ort_inputs = {
            "input": x,
            "state": self._state,
            "sr": np.array(sample_rate, dtype=np.int64),
        }
        out, new_state = self.session.run(None, ort_inputs)

        # Update internal state
        self._state = new_state
        self._context = x[:, -SILERO_CONTEXT_SIZE:]
        self._last_sr = sample_rate
        self._last_batch_size = batch_size

        # Return probability (scalar)
        return float(out[0][0])


def _ensure_model() -> Path:
    """Ensure the ONNX model is downloaded and cached.

    Returns:
        Path to the cached model file.
    """
    if _MODEL_PATH.exists():
        return _MODEL_PATH

    logger.info(f"Downloading Silero VAD ONNX model to {_MODEL_PATH}...")
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    import httpx
    import tempfile
    import shutil

    # Download to temp file first, then move atomically
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=_CACHE_DIR, suffix=".onnx.tmp", delete=False
        ) as tmp:
            tmp_path = tmp.name
            response = httpx.get(_MODEL_URL, follow_redirects=True, timeout=60.0)
            response.raise_for_status()
            tmp.write(response.content)

        shutil.move(tmp_path, _MODEL_PATH)
        tmp_path = None  # Moved successfully, don't clean up
        logger.info(f"Silero VAD model downloaded ({_MODEL_PATH.stat().st_size / 1024:.0f} KB)")
    except Exception:
        # Clean up partial download
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return _MODEL_PATH


# Module-level singleton for lazy loading
_vad_instance: Optional[SileroVAD] = None


def get_silero_vad() -> Optional[SileroVAD]:
    """Get or create the singleton Silero VAD instance.

    Returns:
        SileroVAD instance, or None if loading fails.
    """
    global _vad_instance
    if _vad_instance is None:
        try:
            _vad_instance = SileroVAD()
        except Exception as e:
            logger.warning(f"Failed to load Silero VAD: {e}")
            return None
    return _vad_instance


def detect_speech(audio_chunk: np.ndarray, sample_rate: int) -> Optional[float]:
    """Detect speech in an audio chunk using Silero VAD.

    Convenience function that uses the module-level singleton.

    Args:
        audio_chunk: Audio samples (int16 or float32 numpy array).
            Must be exactly 512 samples at 16kHz.
        sample_rate: Sample rate of the audio.

    Returns:
        Speech probability (0.0 to 1.0), or None if VAD is not available.
    """
    vad = get_silero_vad()
    if vad is None:
        return None
    try:
        return vad(audio_chunk, sample_rate)
    except Exception as e:
        logger.warning(f"Silero VAD inference error: {e}")
        return None


def get_threshold_for_aggressiveness(aggressiveness: int) -> float:
    """Map WebRTC-style aggressiveness (0-3) to Silero probability threshold.

    Args:
        aggressiveness: VAD aggressiveness level (0-3).
            0 = very tolerant of background noise (threshold 0.3)
            1 = default (threshold 0.5)
            2 = stricter (threshold 0.7)
            3 = very strict (threshold 0.85)

    Returns:
        Probability threshold for speech detection.
    """
    return AGGRESSIVENESS_THRESHOLDS.get(aggressiveness, 0.5)
