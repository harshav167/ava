"""VoiceMode Installer - System dependency management and installation."""

try:
    from importlib.metadata import version
    __version__ = version("voice-mode-install")
except Exception:
    # Fallback to version from pyproject.toml if package not installed
    __version__ = "5.1.6"
