"""Test Makefile portability across platforms."""

import subprocess
import platform
import pytest
from pathlib import Path


class TestMakefilePortability:
    """Test that Makefile works on both macOS and Linux."""
    
    def test_sed_commands_are_portable(self):
        """Test that all sed commands use portable syntax."""
        makefile_path = Path(__file__).parent.parent / "Makefile"
        
        with open(makefile_path, 'r') as f:
            makefile_content = f.read()
        
        # Check for problematic sed -i usage (without .bak)
        lines = makefile_content.split('\n')
        problematic_lines = []
        
        for i, line in enumerate(lines, 1):
            # Look for sed -i without .bak (but not sed -i.bak)
            if 'sed -i ' in line and 'sed -i.bak' not in line and 'sed -i.' not in line:
                # Check if it's not followed by a quote or flag
                after_sed = line.split('sed -i ')[1]
                if after_sed and after_sed[0] in ['"', "'", '-']:
                    problematic_lines.append((i, line.strip()))
        
        assert not problematic_lines, (
            f"Found non-portable sed -i commands in Makefile:\n" +
            "\n".join([f"  Line {num}: {line}" for num, line in problematic_lines]) +
            "\n\nUse 'sed -i.bak ... && rm *.bak' for cross-platform compatibility"
        )
    
    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-specific test")
    def test_makefile_targets_on_macos(self):
        """Test that key Makefile targets work on macOS."""
        # Test the clean target which uses find commands
        result = subprocess.run(['make', 'clean'], capture_output=True, text=True)
        assert result.returncode == 0, f"make clean failed: {result.stderr}"
        assert "All build artifacts cleaned!" in result.stdout
    
    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific test")
    def test_makefile_targets_on_linux(self):
        """Test that key Makefile targets work on Linux."""
        # Test the clean target which uses find commands
        result = subprocess.run(['make', 'clean'], capture_output=True, text=True)
        assert result.returncode == 0, f"make clean failed: {result.stderr}"
        assert "All build artifacts cleaned!" in result.stdout
    
    def test_date_command_portability(self):
        """Test that date commands in Makefile are portable."""
        makefile_path = Path(__file__).parent.parent / "Makefile"
        
        with open(makefile_path, 'r') as f:
            makefile_content = f.read()
        
        # GNU date uses different flags than BSD date
        # Check for common non-portable date usage
        if 'date -d' in makefile_content:
            pytest.fail("Found 'date -d' which is GNU-specific. Use portable date syntax.")
        
        if 'date --' in makefile_content and 'date --iso' not in makefile_content:
            pytest.fail("Found GNU-style long options for date. Use portable date syntax.")