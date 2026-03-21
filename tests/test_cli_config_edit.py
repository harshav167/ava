"""Unit tests for the config edit CLI command."""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from click.testing import CliRunner
from voice_mode.cli import voice_mode_main_cli


class TestConfigEditCommand:
    """Test the config edit CLI command."""

    def test_config_edit_help(self):
        """Test that config edit has proper help text."""
        runner = CliRunner()
        result = runner.invoke(voice_mode_main_cli, ['config', 'edit', '--help'])

        assert result.exit_code == 0
        assert 'Open the configuration file' in result.output
        assert '--editor' in result.output
        assert 'voicemode.env' in result.output

    def test_config_edit_help_short_option(self):
        """Test that -h works for help."""
        runner = CliRunner()
        result = runner.invoke(voice_mode_main_cli, ['config', 'edit', '-h'])

        assert result.exit_code == 0
        assert 'Open the configuration file' in result.output

    def test_config_command_lists_edit(self):
        """Test that edit is listed in config command help."""
        runner = CliRunner()
        result = runner.invoke(voice_mode_main_cli, ['config', '--help'])

        assert result.exit_code == 0
        assert 'edit' in result.output
        assert 'Open the configuration file' in result.output


# Import needed for subprocess mock
import subprocess