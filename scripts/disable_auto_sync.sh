#!/bin/bash

# Remove the legacy cron entry if present.
(crontab -l 2>/dev/null | grep -v "auto_push.sh") | crontab -

PLIST_NAME="com.kyle.vibe_sync.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

# Unload and remove the launch agent definition.
launchctl unload "$PLIST_DEST" 2>/dev/null
rm -f "$PLIST_DEST"

echo "❌ Vibe Coding 自動更新已停止！(Launchd 行程已卸載)"
