#!/bin/bash
# voicemode-server.sh — Manage the VoiceMode HTTP server via launchd
#
# Usage:
#   ./scripts/voicemode-server.sh start    # Start server (load launchd)
#   ./scripts/voicemode-server.sh stop     # Stop server (unload launchd)
#   ./scripts/voicemode-server.sh restart  # Stop + start
#   ./scripts/voicemode-server.sh status   # Check if running
#   ./scripts/voicemode-server.sh logs     # Tail server logs
#   ./scripts/voicemode-server.sh setup    # Create/update launchd plist + start

LABEL="com.voicemode.server"
PLIST_SOURCE="$HOME/.voicemode/$LABEL.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/.voicemode/logs"
PORT=8765

# Auto-detect paths
UV_PATH=$(which uv 2>/dev/null || echo "$HOME/.cargo/bin/uv")
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

create_plist() {
    mkdir -p "$LOG_DIR"
    mkdir -p "$(dirname "$PLIST_SOURCE")"

    cat > "$PLIST_SOURCE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$UV_PATH</string>
        <string>run</string>
        <string>--directory</string>
        <string>$PROJECT_DIR</string>
        <string>voicemode</string>
        <string>serve</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>$PORT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/server.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/server.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$(dirname "$UV_PATH"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

    # Symlink to LaunchAgents
    ln -sf "$PLIST_SOURCE" "$PLIST_DEST"
    echo "Created plist: $PLIST_SOURCE"
    echo "Symlinked to: $PLIST_DEST"
}

start_server() {
    if launchctl list | grep -q "$LABEL"; then
        echo "Server already loaded. Use 'restart' to reload."
        return 0
    fi
    launchctl load "$PLIST_DEST" 2>&1
    sleep 3
    if lsof -ti :$PORT > /dev/null 2>&1; then
        echo "Server started on port $PORT"
    else
        echo "Server loaded but not yet listening (check logs)"
    fi
}

stop_server() {
    launchctl unload "$PLIST_DEST" 2>/dev/null
    sleep 2
    # Kill any lingering voicemode processes on the port
    lsof -ti :$PORT 2>/dev/null | while read pid; do
        cmd=$(ps -p "$pid" -o comm= 2>/dev/null)
        if [[ "$cmd" == *python* ]]; then
            kill -9 "$pid" 2>/dev/null
        fi
    done
    echo "Server stopped"
}

case "${1:-status}" in
    setup)
        echo "Setting up VoiceMode server..."
        create_plist
        stop_server 2>/dev/null
        start_server
        echo "Done. Server runs on http://127.0.0.1:$PORT/mcp"
        ;;
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        echo "Restarting..."
        stop_server
        sleep 1
        start_server
        ;;
    status)
        if launchctl list | grep -q "$LABEL"; then
            pid=$(lsof -ti :$PORT 2>/dev/null | head -1)
            if [ -n "$pid" ]; then
                echo "Running (PID: $pid, port: $PORT)"
            else
                echo "Loaded but not listening on port $PORT"
            fi
        else
            echo "Not running (launchd agent not loaded)"
        fi
        ;;
    logs)
        tail -f "$LOG_DIR/server.err"
        ;;
    *)
        echo "Usage: $0 {setup|start|stop|restart|status|logs}"
        exit 1
        ;;
esac
