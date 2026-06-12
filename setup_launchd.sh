#!/bin/bash
# Sets up automatic 48-hour scheduling on Mac using launchd.
# Run once: bash setup_launchd.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.hrengine.pipeline"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PYTHON=$(which python3)
LOG_DIR="$SCRIPT_DIR"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_DIR/run_pipeline.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>GEMINI_API_KEY</key>
        <string>${GEMINI_API_KEY}</string>
    </dict>

    <!-- Run every 48 hours (172800 seconds) -->
    <key>StartInterval</key>
    <integer>172800</integer>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/hr_engine.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/hr_engine_error.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH"

echo "✅ HR Engine scheduled to run every 48 hours."
echo "   Plist: $PLIST_PATH"
echo ""
echo "Useful commands:"
echo "  Run now:    launchctl start $PLIST_NAME"
echo "  Stop:       launchctl unload $PLIST_PATH"
echo "  View log:   tail -f $LOG_DIR/hr_engine.log"
