#!/bin/bash
# Guarded alignment of ~/agent-sync's git bookkeeping to origin/main. Safe to
# call from anywhere, anytime: it never touches a working tree that has any
# real content difference from origin/main (uncommitted edits, or local
# commits not yet pushed), and it never errors out loud when offline.
#
# Called from three places: the git-align watcher launchd (triggered by
# .last-pull changing, i.e. a pull-broadcast from another machine), the
# SessionStart fallback hook, and the nightly job (before the merge/dream
# passes). Content itself always arrives via Syncthing; this script only
# aligns git's HEAD/index to match what's already on disk.
#
# Untracked files (memory/, .last-pull, personal claude/agents|skills|commands)
# are never touched by `git reset --hard` -- it only affects tracked content.
# Deletions of tracked files propagate fine too: Syncthing mirrors the removal
# to every machine before this script ever runs, so `reset --hard` just
# aligns git's bookkeeping to what's already on disk.
set -uo pipefail

DIR="${AGENT_SYNC_DIR:-$HOME/agent-sync}"
LOG="$DIR/setup/logs/git-align.log"

[ -d "$DIR/.git" ] || exit 0

git -C "$DIR" fetch -q origin main 2>/dev/null || exit 0

head=$(git -C "$DIR" rev-parse HEAD 2>/dev/null) || exit 0
origin_head=$(git -C "$DIR" rev-parse origin/main 2>/dev/null) || exit 0
[ "$head" = "$origin_head" ] && exit 0

# Real staged work must never be touched, and the intent-to-add trick below
# needs to start from a clean index (so the `git reset -q` that undoes it is
# a safe no-op restore, never a loss) -- bail immediately if anything is
# staged.
git -C "$DIR" diff --cached --quiet || exit 0

# A file that's new in origin/main but already sitting locally as an
# untracked file (Syncthing delivered the content before this machine's git
# caught up -- true for every file a pull adds) reads as a "deletion" to
# `git diff <commit>`: the index has no entry for that path at all, so the
# diff machinery never looks at what's actually on disk. Intent-to-add those
# specific paths so the content check below compares real bytes instead.
# Scoped deliberately to paths origin/main actually has -- a stray local-only
# untracked file is irrelevant to alignment (reset --hard never touches it)
# and must not be able to block it.
new_paths=()
while IFS= read -r p; do
    [ -n "$p" ] && new_paths+=("$p")
done < <(LC_ALL=C comm -12 \
    <(git -C "$DIR" ls-files --others --exclude-standard | LC_ALL=C sort) \
    <(git -C "$DIR" ls-tree -r --name-only origin/main | LC_ALL=C sort))
if [ "${#new_paths[@]}" -gt 0 ]; then
    git -C "$DIR" add -N -- "${new_paths[@]}"
fi

# Any real content difference (uncommitted edits, local commits not yet
# pushed, or a genuinely different untracked file origin also added) means
# this machine has work that must never be silently destroyed -- leave it
# alone.
if ! git -C "$DIR" diff --quiet origin/main; then
    git -C "$DIR" reset -q  # drop only the intent-to-add markers above
    exit 0
fi

git -C "$DIR" reset --hard -q origin/main
mkdir -p "$(dirname "$LOG")"
echo "$(date '+%F %T') aligned to $(git -C "$DIR" rev-parse --short origin/main)" >> "$LOG"
