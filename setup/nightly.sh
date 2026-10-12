#!/bin/bash
# Nightly maintenance driver (main role only, via launchd). Aligns this
# machine's git bookkeeping to origin/main first, so the merge/dream passes
# below always run against current scripts rather than stale git state.
set -euo pipefail

# launchd supplies only the bare system PATH; make sure claude (and anything
# it spawns) resolves the same way it would in a user shell.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$DIR/setup/git-align.sh"
python3 "$DIR/setup/merge-sync-conflicts.py"
