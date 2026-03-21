#!/usr/bin/env python3
"""Test script for VAD enhancement - waits for speech indefinitely."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice_mode.tools.converse import record_audio_with_silence_detection

async def test_vad_waiting():
    print("Testing VAD enhancement - waiting for speech indefinitely...")
    print("The system will now wait for you to speak.")
    print("Try waiting 5-10 seconds before speaking to test the new behavior.")
    print("Press Ctrl+C to cancel.\n")
    
    try:
        # Test with 30 second max duration
        audio_data, speech_detected = await asyncio.get_event_loop().run_in_executor(
            None, 
            record_audio_with_silence_detection,
            30.0,  # max_duration
            False,  # disable_silence_detection
            0.5,    # min_duration
            2       # vad_aggressiveness
        )
        
        print(f"\nRecording complete!")
        print(f"Speech detected: {speech_detected}")
        print(f"Audio samples recorded: {len(audio_data)}")
        
        if not speech_detected:
            print("\nNo speech was detected during the recording.")
            print("This is the expected behavior - the system waited but you didn't speak.")
        else:
            print("\nSpeech was detected! The system successfully waited for you to speak.")
            
    except KeyboardInterrupt:
        print("\nTest cancelled by user.")
    except Exception as e:
        print(f"\nError during test: {e}")

if __name__ == "__main__":
    asyncio.run(test_vad_waiting())