#!/usr/bin/env python3
"""
Test script for conversation browser playback features.

This tests that the playback UI elements are properly rendered.
"""

import os
import sys
import tempfile
import importlib.util
from datetime import datetime
from pathlib import Path
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Check if Flask is available
HAS_FLASK = importlib.util.find_spec("flask") is not None

def create_test_environment():
    """Create a temporary test environment with sample data."""
    temp_dir = tempfile.mkdtemp(prefix="voicemode_test_")
    base_dir = Path(temp_dir)
    
    # Create directories
    (base_dir / "logs").mkdir()
    (base_dir / "audio").mkdir()
    (base_dir / "transcriptions").mkdir()
    
    # Create sample JSONL log with conversations
    exchanges = [
        {
            "type": "conversation",
            "timestamp": "2025-07-02T10:00:00",
            "conversation_id": "conv-123",
            "project_path": "/test/project",
            "text": "Hello, how can I help you today?",
            "audio_file": "tts_20250702_100000_123.wav",
            "metadata": {
                "model": "tts-1",
                "voice": "nova",
                "provider": "openai",
                "timing": "ttfa: 1.2s, total: 3.5s"
            }
        },
        {
            "type": "stt",
            "timestamp": "2025-07-02T10:00:10",
            "conversation_id": "conv-123",
            "project_path": "/test/project",
            "text": "I need help with the conversation browser playback feature.",
            "audio_file": "stt_20250702_100010_456.wav",
            "metadata": {
                "timing": "duration: 5.2s"
            }
        },
        {
            "type": "conversation",
            "timestamp": "2025-07-02T10:00:20",
            "conversation_id": "conv-123",
            "project_path": "/test/project",
            "text": "I'd be happy to help with the playback feature. What specific aspect are you working on?",
            "audio_file": "tts_20250702_100020_789.wav",
            "metadata": {
                "model": "tts-1",
                "voice": "nova",
                "provider": "openai",
                "timing": "ttfa: 1.1s, total: 4.2s"
            }
        }
    ]
    
    # Write current records through the shared exchange writer; append one
    # malformed line to verify the shared reader keeps tolerant behavior.
    from voice_mode.exchanges.models import Exchange, ExchangeMetadata
    from voice_mode.exchanges.writer import ExchangeWriter

    writer = ExchangeWriter(logs_dir=base_dir / "logs" / "conversations")
    for exchange in exchanges:
        exchange_type = exchange["type"]
        if exchange_type == "conversation":
            exchange_type = "tts"
        writer.append(
            Exchange(
                version=3,
                timestamp=datetime.fromisoformat(exchange["timestamp"]),
                conversation_id=exchange["conversation_id"],
                type=exchange_type,
                text=exchange["text"],
                project_path=exchange.get("project_path"),
                audio_file=exchange.get("audio_file"),
                metadata=ExchangeMetadata.from_dict(exchange.get("metadata", {})),
            )
        )

    jsonl_path = next((base_dir / "logs" / "conversations").glob("exchanges_*.jsonl"))
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write("{malformed json}\n")
    
    # Create dummy audio files
    for exchange in exchanges:
        if exchange.get("audio_file"):
            audio_path = base_dir / "audio" / exchange["audio_file"]
            # Create a simple WAV header (44 bytes) + minimal data
            wav_header = b'RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x02\x00\x22\x56\x00\x00\x88\x58\x01\x00\x04\x00\x10\x00data\x00\x08\x00\x00'
            audio_path.write_bytes(wav_header + b'\x00' * 2048)
    
    return base_dir

@pytest.mark.skipif(not HAS_FLASK, reason="Flask not installed (install with 'pip install voice-mode[scripts]')")
def test_playback_ui():
    """Test that playback UI elements are rendered correctly."""
    # Create test environment
    test_dir = create_test_environment()
    
    # Set environment variable
    os.environ["VOICEMODE_BASE_DIR"] = str(test_dir)
    
    try:
        # Import after setting env var
        from scripts.conversation_browser import app, get_all_exchanges, group_exchanges_into_conversations
        
        # Test data loading
        exchanges = get_all_exchanges()
        print(f"✓ Loaded {len(exchanges)} exchanges")
        
        # Test conversation grouping
        conversations = group_exchanges_into_conversations(exchanges)
        print(f"✓ Grouped into {len(conversations)} conversations")
        
        # Test Flask app
        app.config['TESTING'] = True
        client = app.test_client()
        
        # Test conversation view
        response = client.get('/?view=conversation')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        
        # Check for playback UI elements
        checks = [
            ('Select All checkbox', 'class="select-all-checkbox"', html),
            ('Play Conversation button', 'class="play-all-button"', html),
            ('Individual play buttons', 'class="play-button"', html),
            ('Conversation checkboxes', 'class="conversation-checkbox"', html),
            ('Audio controls div', 'class="audio-controls"', html),
            ('Playback JavaScript', 'function playAudio', html),
            ('Playlist functionality', 'function playConversation', html),
            ('Select all functionality', 'function toggleSelectAll', html),
        ]
        
        print("\nUI Element Checks:")
        all_passed = True
        for name, search_str, content in checks:
            if search_str in content:
                print(f"  ✓ {name}")
            else:
                print(f"  ✗ {name} - NOT FOUND")
                all_passed = False
        
        # Count specific elements
        select_all_count = html.count('class="select-all-checkbox"')
        play_button_count = html.count('class="play-button"')
        checkbox_count = html.count('class="conversation-checkbox"')
        
        print("\nElement Counts:")
        print(f"  - Select All checkboxes: {select_all_count}")
        print(f"  - Play buttons: {play_button_count}")
        print(f"  - Conversation checkboxes: {checkbox_count}")
        
        if all_passed:
            print("\n✅ All playback UI elements are present!")
        else:
            print("\n❌ Some playback UI elements are missing!")
            
    finally:
        # Cleanup
        import shutil
        shutil.rmtree(test_dir)
        print("\n✓ Cleaned up test directory")

if __name__ == "__main__":
    print("Testing Conversation Browser Playback Features")
    print("=" * 50)
    test_playback_ui()