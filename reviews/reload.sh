#!/bin/bash
launchctl unload ~/Library/LaunchAgents/com.journal.watcher.plist 2>/dev/null
launchctl unload ~/Library/LaunchAgents/com.journal.overnight-review.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.journal.watcher.plist
launchctl load ~/Library/LaunchAgents/com.journal.overnight-review.plist
echo "Reloaded"
