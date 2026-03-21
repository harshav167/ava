#!/usr/bin/env python3
"""
Process README.md for MkDocs by fixing relative links.
Removes 'docs/' prefix from links so they work correctly when README is in docs dir.
"""
import re
import sys

def process_readme(input_file, output_file):
    """Process README.md to fix links for MkDocs."""
    with open(input_file, 'r') as f:
        content = f.read()
    
    # Remove docs/ prefix from markdown links
    # Pattern matches [text](docs/path) and converts to [text](path)
    content = re.sub(r'\[([^\]]+)\]\(docs/([^)]+)\)', r'[\1](\2)', content)
    
    with open(output_file, 'w') as f:
        f.write(content)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: process-readme-for-docs.py <input> <output>")
        sys.exit(1)
    
    process_readme(sys.argv[1], sys.argv[2])