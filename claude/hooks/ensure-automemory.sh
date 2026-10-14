#!/bin/bash
# SessionStart hook: ensure this git project's auto-memory points into ~/agent-sync.
# autoMemoryDirectory is only honored from settings.local.json / user settings
# (checked-in .claude/settings.json is ignored for this key), so each machine
# generates the local file deterministically from the repo folder name.
set -u
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
name=$(basename "$root")
mkdir -p "$root/.claude"
python3 - "$root/.claude/settings.local.json" "$name" <<'PY'
import json, os, sys
path, name = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        sys.exit(0)  # never clobber a malformed file
if "autoMemoryDirectory" in data:
    sys.exit(0)
data["autoMemoryDirectory"] = f"~/agent-sync/memory/{name}"
os.makedirs(os.path.expanduser(f"~/agent-sync/memory/{name}"), exist_ok=True)
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, path)
PY
# Migrate legacy per-project memory (pre-agent-sync ~/.claude/projects/<key>/memory)
# into the shared folder. Claude Code's key is the session cwd with every
# non-alphanumeric character turned into '-'. Copy file-by-file without
# overwriting and keep originals, so cluster machines sharing memory/ via
# Syncthing each contribute their own legacy files. Runs once per machine and
# source key — tracked by a local marker file — because nightly curation
# deletes/merges migrated files and a re-run of cp -n would resurrect them.
dst="$HOME/agent-sync/memory/$name"
for p in "$PWD" "$root"; do
    key=$(printf '%s' "$p" | sed 's|[^A-Za-z0-9]|-|g')
    src="$HOME/.claude/projects/$key/memory"
    [ -d "$src" ] || continue
    mark="$HOME/.claude/agent-sync-migrated/$key"
    [ -e "$mark" ] && continue
    mkdir -p "$dst"
    cp -Rn "$src/." "$dst/" 2>/dev/null || true
    mkdir -p "${mark%/*}"
    : > "$mark"
done
# Keep .claude out of accidental commits without touching the shared .gitignore
if ! git -C "$root" check-ignore -q .claude 2>/dev/null; then
    gitdir=$(git -C "$root" rev-parse --absolute-git-dir 2>/dev/null) || exit 0
    mkdir -p "$gitdir/info"
    grep -qxF ".claude/" "$gitdir/info/exclude" 2>/dev/null || echo ".claude/" >> "$gitdir/info/exclude"
fi
exit 0
