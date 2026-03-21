#!/usr/bin/env bash
# Setup npm to install global packages without sudo
# Works on macOS and Linux
# This script is idempotent - safe to run multiple times

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Helper functions
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect shell configuration file
detect_shell_config() {
    if [[ -n "${BASH_VERSION:-}" ]]; then
        if [[ -f "$HOME/.bash_profile" ]]; then
            echo "$HOME/.bash_profile"
        else
            echo "$HOME/.bashrc"
        fi
    elif [[ -n "${ZSH_VERSION:-}" ]]; then
        echo "$HOME/.zshrc"
    else
        # Default to bashrc if we can't detect
        echo "$HOME/.bashrc"
    fi
}

main() {
    info "Setting up npm to install global packages without sudo..."
    
    # Check if npm is installed
    if ! command -v npm &> /dev/null; then
        error "npm is not installed. Please install Node.js and npm first."
        exit 1
    fi
    
    NPM_GLOBAL_DIR="$HOME/.npm-global"
    SHELL_CONFIG=$(detect_shell_config)
    
    # Check current npm prefix
    CURRENT_PREFIX=$(npm config get prefix 2>/dev/null || echo "")
    
    # Check if already configured
    if [[ "$CURRENT_PREFIX" == "$NPM_GLOBAL_DIR" ]]; then
        success "npm is already configured to use $NPM_GLOBAL_DIR"
    else
        # Create npm global directory
        if [[ ! -d "$NPM_GLOBAL_DIR" ]]; then
            info "Creating $NPM_GLOBAL_DIR directory..."
            mkdir -p "$NPM_GLOBAL_DIR"
        fi
        
        # Configure npm prefix
        info "Configuring npm to use $NPM_GLOBAL_DIR..."
        npm config set prefix "$NPM_GLOBAL_DIR"
        success "npm prefix set to $NPM_GLOBAL_DIR"
    fi
    
    # Check if PATH already contains npm-global/bin
    if [[ ":$PATH:" == *":$NPM_GLOBAL_DIR/bin:"* ]]; then
        success "PATH already includes $NPM_GLOBAL_DIR/bin"
    else
        # Add to PATH in shell config
        info "Adding $NPM_GLOBAL_DIR/bin to PATH in $SHELL_CONFIG..."
        
        # Check if the export line already exists in shell config
        if grep -q "export PATH=\"\$HOME/.npm-global/bin:\$PATH\"" "$SHELL_CONFIG" 2>/dev/null; then
            warning "PATH export already exists in $SHELL_CONFIG"
        else
            # Add export to shell config
            echo '' >> "$SHELL_CONFIG"
            echo '# npm global packages path (added by setup-npm-global.sh)' >> "$SHELL_CONFIG"
            echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$SHELL_CONFIG"
            success "Added PATH export to $SHELL_CONFIG"
            
            warning "You need to reload your shell configuration:"
            echo "  Run: source $SHELL_CONFIG"
            echo "  Or start a new terminal session"
        fi
    fi
    
    echo ""
    success "npm global setup complete!"
    echo ""
    info "You can now install global packages without sudo:"
    echo "  npm install -g <package-name>"
    echo ""
    
    # Show current configuration
    info "Current configuration:"
    echo "  npm prefix: $(npm config get prefix)"
    echo "  Shell config: $SHELL_CONFIG"
    
    # Check if we need to reload
    if [[ ":$PATH:" != *":$NPM_GLOBAL_DIR/bin:"* ]]; then
        echo ""
        warning "Don't forget to reload your shell configuration!"
        echo "  Run: source $SHELL_CONFIG"
    fi
}

# Run main function
main "$@"