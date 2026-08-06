#!/bin/bash
# Nightly maintenance driver (main role only, via launchd). Aligns this
# machine's git bookkeeping to origin/main first, so the merge/dream passes
# below always run against current scripts rather than stale git state.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$DIR/setup/git-align.sh"
python3 "$DIR/setup/merge-sync-conflicts.py"
