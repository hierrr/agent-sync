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
# Keep .claude out of accidental commits without touching the shared .gitignore
if ! git -C "$root" check-ignore -q .claude 2>/dev/null; then
    gitdir=$(git -C "$root" rev-parse --absolute-git-dir 2>/dev/null) || exit 0
    mkdir -p "$gitdir/info"
    grep -qxF ".claude/" "$gitdir/info/exclude" 2>/dev/null || echo ".claude/" >> "$gitdir/info/exclude"
fi
exit 0
