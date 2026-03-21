#!/usr/bin/env python3
"""Test STT directly with saved audio files to diagnose the issue."""

import os
import sys
import asyncio
import logging
from pathlib import Path
from openai import AsyncOpenAI
from pydub import AudioSegment
import tempfile

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_stt_with_file(audio_file: Path):
    """Test STT with a specific audio file."""
    logger.info(f"Testing STT with file: {audio_file}")
    
    # Initialize OpenAI client
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Test 1: Direct WAV file upload
    logger.info("Test 1: Direct WAV upload")
    try:
        with open(audio_file, 'rb') as f:
            transcription = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text"
            )
            logger.info(f"✓ Direct WAV result: '{transcription}'")
    except Exception as e:
        logger.error(f"✗ Direct WAV failed: {e}")
    
    # Test 2: Convert to MP3 (like voice-mode does)
    logger.info("\nTest 2: Convert to MP3 first")
    try:
        audio = AudioSegment.from_wav(str(audio_file))
        logger.info(f"Audio stats - Duration: {len(audio)}ms, Channels: {audio.channels}, Frame rate: {audio.frame_rate}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as mp3_file:
            audio.export(mp3_file.name, format="mp3", bitrate="64k")
            logger.info(f"MP3 created: {mp3_file.name} ({os.path.getsize(mp3_file.name)} bytes)")
            
            with open(mp3_file.name, 'rb') as f:
                transcription = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="text"
                )
                logger.info(f"✓ MP3 result: '{transcription}'")
            
            os.unlink(mp3_file.name)
    except Exception as e:
        logger.error(f"✗ MP3 conversion failed: {e}")
    
    # Test 3: Check audio content
    logger.info("\nTest 3: Audio content analysis")
    try:
        import numpy as np
        from scipy.io import wavfile
        
        rate, data = wavfile.read(str(audio_file))
        logger.info(f"Sample rate: {rate}Hz, Data shape: {data.shape}, dtype: {data.dtype}")
        logger.info(f"Audio stats - Min: {data.min()}, Max: {data.max()}, Mean: {data.mean():.2f}")
        
        # Check RMS to see if it's actual audio
        rms = np.sqrt(np.mean(data.astype(float) ** 2))
        logger.info(f"RMS level: {rms:.2f} ({'likely silence' if rms < 100 else 'audio detected'})")
    except Exception as e:
        logger.error(f"✗ Audio analysis failed: {e}")

async def main():
    """Main test function."""
    # Get the latest audio file
    audio_dir = Path.home() / "voicemode_audio"
    audio_files = sorted(audio_dir.glob("*-stt.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not audio_files:
        logger.error("No audio files found in ~/voicemode_audio/")
        return
    
    # Test the most recent file
    latest_file = audio_files[0]
    await test_stt_with_file(latest_file)
    
    # Also test a specific file if provided as argument
    if len(sys.argv) > 1:
        specific_file = Path(sys.argv[1])
        if specific_file.exists():
            logger.info("\n" + "="*50 + "\n")
            await test_stt_with_file(specific_file)

if __name__ == "__main__":
    asyncio.run(main())