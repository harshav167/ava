"""Shared initialization for voicemode."""

import subprocess


# Import all configuration from config.py
from .config import (
    service_processes,
    logger,
)

# All configuration imported from config.py
# Track if startup has been initialized
_startup_initialized = False


# Sounddevice workaround already applied in config.py


async def startup_initialization():
    """Initialize services on startup based on configuration"""
    global _startup_initialized

    if _startup_initialized:
        return

    _startup_initialized = True
    logger.info("Running startup initialization...")

    # Log initial status
    logger.info("Service initialization complete")


def cleanup_on_shutdown():
    """Cleanup function called on shutdown"""
    # Stop any services we started
    for name, process in service_processes.items():
        if process and process.poll() is None:
            logger.info(f"Stopping {name} service (PID: {process.pid})...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            logger.info(f"✓ {name} service stopped")
