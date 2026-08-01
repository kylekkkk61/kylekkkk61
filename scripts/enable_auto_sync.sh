#!/bin/bash

# Remove the legacy cron entry if present.
(crontab -l 2>/dev/null | grep -v "auto_push.sh") | crontab -

PLIST_NAME="com.kyle.vibe_sync.plist"
PLIST_SRC="/Users/kyle/Projects/kylekkkk61/scripts/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

# Install the launch agent definition.
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"

# Reload the launch agent, ignoring a missing previous installation.
launchctl unload "$PLIST_DEST" 2>/dev/null
launchctl load "$PLIST_DEST"

echo "✅ Vibe Coding 自動更新已升級為 Launchd 守護行程！"
echo "系統將在每天半夜 12:00 背景自動結算戰績並更新至 GitHub。"
echo "如果您在半夜蓋上筆電，它會在您早上打開螢幕的第一秒立刻補執行！"
