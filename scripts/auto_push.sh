#!/bin/bash

set -euo pipefail

# Include user-installed tools for launchd.
export PATH="/Users/kyle/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Switch to the repository.
cd /Users/kyle/Projects/kylekkkk61

# Update README.md.
uv run scripts/vibe_tracker.py

# Commit only when the generated files changed.
if ! git diff --quiet -- README.md .vibe_stats.json || \
   ! git ls-files --error-unmatch .vibe_stats.json >/dev/null 2>&1; then
    git add README.md .vibe_stats.json
    git commit -m "auto-update vibe stats"

    # Push to the configured default branch.
    git push origin main 2>/dev/null || git push origin master 2>/dev/null
fi
