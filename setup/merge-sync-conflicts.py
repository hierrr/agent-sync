#!/usr/bin/env python3
"""Nightly maintenance for ~/agent-sync (runs on the main machine only).

memory/ — resolves Syncthing conflict files left by simultaneous edits:
- MEMORY.md conflicts: union of lines (original order first), conflict file removed.
- Other .md conflicts: kept as '<stem>-alt-N.md' plus an index line flagged for
  review, so no version of a memory is ever silently dropped. Claude Code's
  built-in auto-dream consolidation then cleans these up over time.

claude/ (agents·skills·commands) — same-name conflicts are merged by a headless
Claude call ("keep both" is not an option here: every .md under agents/ is a live
agent definition). Both source versions are archived to setup/logs/conflict-archive/
before the merged file is written; on any failure the conflict file is left in
place for the next session's agent to handle.
"""
import glob
import os
import re
import shutil
import subprocess
import time

ROOT = os.path.expanduser("~/agent-sync/memory")
LOG = []

# Built-in auto-dream leaves .consolidate-lock behind after a hard kill and then
# silently never runs again (claude-code GitHub #50694). Dreams take minutes, so
# any lock older than 6h is stale. Age-based (not PID-based) on purpose: locks
# sync across machines here, and a PID only means something on the machine that
# wrote it.
for lock in glob.glob(f"{ROOT}/**/.consolidate-lock", recursive=True):
    try:
        if time.time() - os.path.getmtime(lock) > 6 * 3600:
            os.remove(lock)
            LOG.append(f"removed stale dream lock: {lock}")
    except OSError:
        pass

for conflict in glob.glob(f"{ROOT}/**/*sync-conflict*", recursive=True):
    directory = os.path.dirname(conflict)
    base_name = re.sub(r"\.sync-conflict-[^.]*", "", os.path.basename(conflict))
    original = os.path.join(directory, base_name)

    if not os.path.exists(original):
        os.rename(conflict, original)
        LOG.append(f"restored missing original: {original}")
        continue

    with open(conflict) as f:
        conflict_lines = f.read().splitlines()
    with open(original) as f:
        original_lines = f.read().splitlines()

    if conflict_lines == original_lines:
        os.remove(conflict)
        continue

    if base_name == "MEMORY.md":
        seen = set(original_lines)
        merged = original_lines + [l for l in conflict_lines if l.strip() and l not in seen]
        with open(original, "w") as f:
            f.write("\n".join(merged) + "\n")
        os.remove(conflict)
        LOG.append(f"merged index: {original}")
    else:
        stem, ext = os.path.splitext(base_name)
        n = 1
        while os.path.exists(alt := os.path.join(directory, f"{stem}-alt-{n}{ext}")):
            n += 1
        os.rename(conflict, alt)
        index = os.path.join(directory, "MEMORY.md")
        if os.path.exists(index):
            with open(index, "a") as f:
                f.write(f"- [{stem}-alt-{n}]({os.path.basename(alt)}) — sync conflict of {base_name}; needs review\n")
        LOG.append(f"kept both versions: {alt}")

CLAUDE_ROOT = os.path.expanduser("~/agent-sync/claude")
ARCHIVE = os.path.expanduser("~/agent-sync/setup/logs/conflict-archive")
CLAUDE_BIN = next((c for c in [shutil.which("claude"),
                               os.path.expanduser("~/.claude/local/claude"),
                               "/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
                   if c and os.path.exists(c)), None)

MERGE_PROMPT = """Two versions of the same Claude Code definition file (an agent, skill, \
or command) diverged on two synced machines. Produce ONE merged file that keeps the \
intent and the best elements of both. Output ONLY the merged file content — no code \
fences, no commentary.

--- VERSION A (current file) ---
{a}
--- VERSION B (conflict copy) ---
{b}"""

for conflict in glob.glob(f"{CLAUDE_ROOT}/**/*sync-conflict*", recursive=True):
    directory = os.path.dirname(conflict)
    base_name = re.sub(r"\.sync-conflict-[^.]*", "", os.path.basename(conflict))
    original = os.path.join(directory, base_name)

    if not os.path.exists(original):
        os.rename(conflict, original)
        LOG.append(f"restored missing original: {original}")
        continue
    with open(conflict) as f:
        conflict_text = f.read()
    with open(original) as f:
        original_text = f.read()
    if conflict_text == original_text:
        os.remove(conflict)
        continue
    if not base_name.endswith(".md") or CLAUDE_BIN is None:
        LOG.append(f"left for manual review: {conflict}")
        continue
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", "sonnet"],
            input=MERGE_PROMPT.format(a=original_text, b=conflict_text),
            capture_output=True, text=True, timeout=600)
        merged = result.stdout.strip()
    except Exception as exc:
        LOG.append(f"AI merge error ({exc}); left for manual review: {conflict}")
        continue
    plausible = (result.returncode == 0 and merged
                 and len(merged) >= min(len(original_text), len(conflict_text)) // 2
                 and (not original_text.startswith("---") or merged.startswith("---")))
    if not plausible:
        LOG.append(f"AI merge implausible; left for manual review: {conflict}")
        continue
    os.makedirs(ARCHIVE, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(original, os.path.join(ARCHIVE, f"{stamp}-{base_name}.a"))
    shutil.copy2(conflict, os.path.join(ARCHIVE, f"{stamp}-{base_name}.b"))
    with open(original, "w") as f:
        f.write(merged.rstrip("\n") + "\n")
    os.remove(conflict)
    LOG.append(f"AI-merged: {original}")

print("\n".join(LOG) if LOG else "no conflicts")
