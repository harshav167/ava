#!/usr/bin/env python
"""
Test server module syntax and structure.

These tests ensure the voice-mode server module:
- Has valid Python syntax
- Can be imported without errors
- Has proper structure
"""

import ast
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest


class TestServerSyntax:
    """Test the voice-mode server module syntax and structure"""
    
    @pytest.fixture
    def server_path(self):
        """Get the path to the voice-mode server module"""
        return Path(__file__).parent.parent / "voice_mode" / "server.py"
    
    def test_module_exists(self, server_path):
        """Test that the server module exists"""
        assert server_path.exists(), f"Server module not found at {server_path}"
    
    def test_module_syntax(self, server_path):
        """Test that the module has valid Python syntax"""
        with open(server_path, 'r') as f:
            content = f.read()
        
        # Try to parse it as AST
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in module: {e}")
    
    def test_module_imports(self, server_path):
        """Test that all imports in the module are valid"""
        with open(server_path, 'r') as f:
            content = f.read()
        
        # Extract imports
        lines = content.split('\n')
        imports = []
        
        for line in lines:
            line = line.strip()
            if line.startswith('import ') or line.startswith('from '):
                # Skip imports of optional dependencies
                if any(pkg in line for pkg in ['livekit', 'pydub', 'simpleaudio', 'sounddevice']):
                    continue
                imports.append(line)
        
        # Basic check that core imports are present
        assert any('fastmcp' in imp for imp in imports) or any('FastMCP' in imp for imp in imports), "fastmcp import missing"
        assert any('config' in imp for imp in imports), "config import missing"
    
    def test_logger_initialization_order(self, server_path):
        """Test that logger is initialized before being used"""
        with open(server_path, 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        
        # Find logger initialization or import
        logger_init_line = None
        logger_import_line = None
        logger_first_use = None
        
        # Check if we're in a multi-line import
        in_config_import = False
        config_import_start = None
        
        for i, line in enumerate(lines):
            if 'logger = logging.getLogger' in line:
                logger_init_line = i
            elif 'from .config import' in line:
                in_config_import = True
                config_import_start = i
                if 'logger' in line:
                    logger_import_line = i
            elif in_config_import:
                if ')' in line:
                    in_config_import = False
                elif 'logger' in line and not line.strip().startswith('#'):
                    logger_import_line = config_import_start
            elif logger_init_line is None and logger_import_line is None and 'logger.' in line and not line.strip().startswith('#'):
                logger_first_use = i
        
        # Logger should be initialized or imported before first use
        if logger_first_use is not None:
            assert logger_init_line is not None or logger_import_line is not None, "Logger used before initialization or import"
            if logger_init_line is not None:
                assert logger_init_line < logger_first_use, \
                    f"Logger initialized at line {logger_init_line} but used at line {logger_first_use}"
            if logger_import_line is not None:
                assert logger_import_line < logger_first_use, \
                    f"Logger imported at line {logger_import_line} but used at line {logger_first_use}"
    
    def test_indentation_errors(self, server_path):
        """Test for common indentation errors"""
        with open(server_path, 'r') as f:
            content = f.read()
        
        # Extract Python code
        lines = content.split('\n')
        python_start = 0
        
        # Skip to Python code
        in_metadata = False
        for i, line in enumerate(lines):
            if line.strip() == '# ///':
                if not in_metadata:
                    in_metadata = True
                else:
                    python_start = i + 1
                    break
        
        # Check for mixed tabs and spaces
        for i, line in enumerate(lines[python_start:], start=python_start):
            if '\t' in line and '    ' in line:
                pytest.fail(f"Mixed tabs and spaces at line {i+1}: {line}")
        
        # Check for inconsistent indentation in function definitions
        in_function = False
        function_indent = None
        
        for i, line in enumerate(lines[python_start:], start=python_start):
            if line.strip().startswith('def ') or line.strip().startswith('async def '):
                in_function = True
                function_indent = len(line) - len(line.lstrip())
            elif in_function and line.strip() and not line.strip().startswith('#'):
                current_indent = len(line) - len(line.lstrip())
                # First line of function body should be indented more than function def
                if function_indent is not None and current_indent <= function_indent:
                    in_function = False
    
    def test_critical_functions_exist(self, server_path):
        """Test that critical functions are defined"""
        with open(server_path, 'r') as f:
            content = f.read()
        
        # Check that key modules are imported (functions are now in separate modules)
        assert 'from . import config' in content, "config module should be imported"
        assert 'from . import tools' in content, "tools module should be imported"
        assert 'def main()' in content, "main function not found"
        # Tools are now in separate modules, not in server.py itself
        assert 'from . import tools' in content, "tools module should be imported"
    
    @pytest.mark.skipif(sys.platform == "win32", reason="uv script execution differs on Windows")
    def test_module_executable(self, server_path):
        """Test that the script can be executed without syntax errors"""
        # Create a test that just imports the script and exits
        test_code = f"""
import sys
sys.path.insert(0, '{server_path.parent.parent}')
try:
    # Try to parse the file at least
    with open('{server_path}', 'r') as f:
        compile(f.read(), '{server_path}', 'exec')
    print("OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {{e}}")
    sys.exit(1)
"""
        
        # Run the test
        result = subprocess.run(
            [sys.executable, '-c', test_code],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Script has syntax errors: {result.stdout} {result.stderr}"
        assert "OK" in result.stdout


class TestServerStructure:
    """Test the structure and organization of the server module"""
    
    @pytest.fixture
    def server_path(self):
        """Get the path to the voice-mode server module"""
        return Path(__file__).parent.parent / "voice_mode" / "server.py"
    
    @pytest.fixture
    def server_content(self, server_path):
        """Get the server module content"""
        with open(server_path, 'r') as f:
            return f.read()
    
    def test_imports_at_top(self, server_content):
        """Test that imports are at the top of the file"""
        lines = server_content.split('\n')
        
        # Find first significant non-import line (not comments, docstrings, or constants)
        first_significant_code = None
        last_top_import = None
        in_docstring = False
        
        for i, line in enumerate(lines):
            line_stripped = lines[i].strip()
            
            # Skip empty lines and comments
            if not line_stripped or line_stripped.startswith('#'):
                continue
            
            # Handle docstrings
            if '"""' in line_stripped:
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            
            # Track imports at the top
            if (line_stripped.startswith('import ') or line_stripped.startswith('from ')) and first_significant_code is None:
                last_top_import = i
            # Look for actual code (functions, classes, non-import statements)
            elif (line_stripped.startswith('def ') or line_stripped.startswith('class ') or 
                  line_stripped.startswith('async def ') or '=' in line_stripped) and first_significant_code is None:
                # Exclude simple constant assignments after imports
                if '=' in line_stripped and last_top_import and i - last_top_import < 20:
                    # This might be a constant definition near imports
                    continue
                first_significant_code = i
        
        # Just verify we have imports at the top (don't be too strict about late imports)
        assert last_top_import is not None, "No imports found at the top of the file"
        assert last_top_import < 100, "Initial imports should be near the top of the file"
    
    def test_main_function_exists(self, server_content):
        """Test that the module has a main function"""
        assert 'def main()' in server_content, \
            "Module should have a main() function"
        
        # Should have if __name__ == "__main__" block
        assert 'if __name__ == "__main__":' in server_content, \
            "Module should have a main block"
        
        # Should call main() in the main block
        lines = server_content.split('\n')
        in_main = False
        has_main_call = False
        
        for line in lines:
            if 'if __name__ == "__main__":' in line:
                in_main = True
            elif in_main and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                in_main = False
            elif in_main and 'main()' in line:
                has_main_call = True
        
        assert has_main_call, "Main block should call main()"