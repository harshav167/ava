"""macOS audio ducking — pause/resume media apps during VoiceMode TTS and STT.

Uses media key simulation (via CGEvent / pyobjc-framework-Quartz) to send
the system-wide Play/Pause key.  Before sending, we check whether Spotify
or Apple Music is actually *playing* so we can resume only what was active.

Falls back gracefully when:
  - pyobjc-framework-Quartz is not installed  (no-op)
  - Neither Spotify nor Music is running       (no-op)
  - osascript calls fail                       (no-op)
"""

from __future__ import annotations

import logging
import subprocess
from contextlib import contextmanager

logger = logging.getLogger("voicemode")

# ---------------------------------------------------------------------------
# Detect what's playing
# ---------------------------------------------------------------------------

def _is_app_running(name: str) -> bool:
    """Return True if *name* appears in the macOS process list."""
    try:
        r = subprocess.run(
            [
                "osascript", "-e",
                f'tell application "System Events" to (name of processes) contains "{name}"',
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return r.stdout.strip() == "true"
    except Exception:
        return False


def _is_app_playing(name: str) -> bool:
    """Return True if a media app is currently in the *playing* state."""
    if not _is_app_running(name):
        return False
    try:
        r = subprocess.run(
            [
                "osascript", "-e",
                f'tell application "{name}" to player state as string',
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return r.stdout.strip() == "playing"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Media-key simulation
# ---------------------------------------------------------------------------

def _simulate_media_play_pause() -> None:
    """Send the system media Play/Pause key via CGEvent (Quartz)."""
    try:
        import Quartz  # pyobjc-framework-Quartz
    except ImportError:
        logger.debug("pyobjc-framework-Quartz not installed — media key simulation unavailable")
        return

    try:
        NS_SYSTEM_DEFINED = 14
        NX_KEYTYPE_PLAY = 16

        for key_down in (True, False):
            flags = 0xA00 if key_down else 0xB00
            data1 = (NX_KEYTYPE_PLAY << 16) | ((0xA if key_down else 0xB) << 8)

            ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                NS_SYSTEM_DEFINED,
                (0, 0),
                flags,
                0,
                0,
                0,
                8,
                data1,
                -1,
            )
            Quartz.CGEventPost(0, ev.CGEvent())
    except Exception as e:
        logger.debug(f"Media key simulation failed: {e}")


# ---------------------------------------------------------------------------
# Public context manager
# ---------------------------------------------------------------------------

@contextmanager
def DJDucker():
    """Duck (pause) other audio during TTS playback or mic recording.

    On enter:  detect playing apps → send Play/Pause to pause them.
    On exit:   if we paused something → send Play/Pause to resume.

    Designed as a drop-in replacement for the old mpv-IPC-based DJDucker.
    """
    # Check known scriptable apps
    spotify_was_playing = _is_app_playing("Spotify")
    music_was_playing = _is_app_playing("Music")

    # Also check if ANY Now Playing source is active (covers browser audio, etc.)
    now_playing_active = False
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get (name of processes whose background only is false) as string'],
            capture_output=True, text=True, timeout=2,
        )
        # If we detected known players, that's enough
        now_playing_active = spotify_was_playing or music_was_playing
    except Exception:
        pass

    should_duck = spotify_was_playing or music_was_playing

    if should_duck:
        playing = []
        if spotify_was_playing:
            playing.append("Spotify")
        if music_was_playing:
            playing.append("Music")
        logger.info(f"Ducking audio — pausing {', '.join(playing)}")
        _simulate_media_play_pause()

    try:
        yield
    finally:
        if should_duck:
            logger.info("Unducking audio — resuming playback")
            _simulate_media_play_pause()
