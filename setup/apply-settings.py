#!/usr/bin/env python3
"""Merge agent-sync shared base settings into this machine's ~/.claude/settings.json.

Base keys win for scalars and env entries; machine-local keys (permissions, model,
effortLevel, UI prefs, ...) are left untouched. Hook entries are identified by their
command string containing 'agent-sync' and replaced in place, so re-running is
idempotent and never duplicates hooks.
"""
import json
import os
import shutil
import sys

BASE = os.path.expanduser("~/agent-sync/claude/settings.base.json")
TARGET = os.path.expanduser("~/.claude/settings.json")

with open(BASE) as f:
    base = json.load(f)

target = {}
if os.path.exists(TARGET):
    with open(TARGET) as f:
        target = json.load(f)
    if not os.path.exists(TARGET + ".pre-agent-sync.bak"):
        shutil.copy2(TARGET, TARGET + ".pre-agent-sync.bak")

for key, value in base.items():
    if key == "env":
        target.setdefault("env", {}).update(value)
    elif key == "hooks":
        hooks = target.setdefault("hooks", {})
        for event, base_matchers in value.items():
            existing = hooks.setdefault(event, [])
            # Drop previous agent-sync entries, then append current ones
            for matcher in existing:
                matcher["hooks"] = [
                    h for h in matcher.get("hooks", [])
                    if "agent-sync" not in h.get("command", "")
                ]
            hooks[event] = [m for m in existing if m.get("hooks")] + base_matchers
    elif key == "permissions":
        continue  # permissions always stay machine-local
    else:
        target[key] = value

tmp = TARGET + ".tmp"
with open(tmp, "w") as f:
    json.dump(target, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, TARGET)
print(f"applied {BASE} -> {TARGET}")
