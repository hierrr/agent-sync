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

dream pass (pass 4) — once the conflict passes above have settled memory/, a
headless Claude call curates each memory/<project>/ directory (and _global/) in
place: merges duplicate/contradictory facts, folds "-alt-N" review copies back
into their base file, absolutizes relative dates, moves project-agnostic facts
into _global/GLOBAL.md, and rebuilds MEMORY.md. A directory is skipped if the
built-in auto-dream lock is present, or if nothing in it changed since its own
last successful dream run (tracked in setup/logs/dream-state.json). Every
directory is archived to setup/logs/dream-archive/ before the call and restored
verbatim if the call errors, times out, or fails its post-run sanity checks —
so a bad run never loses data, it just leaves that directory for next time.
Project-dir runs are also allowed to touch one file outside their own
directory — _global/GLOBAL.md, for fact promotion — so that file is archived
and guarded alongside the project dir and restored atomically with it if
either fails.

Testing overrides (both fall back to the real locations when unset):
- AGENT_SYNC_ROOT points memory/, claude/, and setup/logs/ at a fixture tree
  instead of ~/agent-sync.
- AGENT_SYNC_CLAUDE_BIN points at a stub "claude" binary instead of the real CLI.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone

AGENT_SYNC_ROOT = os.environ.get("AGENT_SYNC_ROOT") or os.path.expanduser("~/agent-sync")
ROOT = os.path.join(AGENT_SYNC_ROOT, "memory")
LOG = []


def find_claude_bin():
    override = os.environ.get("AGENT_SYNC_CLAUDE_BIN")
    if override and os.path.exists(override):
        return override
    return next((c for c in [shutil.which("claude"),
                             os.path.expanduser("~/.claude/local/claude"),
                             "/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
                if c and os.path.exists(c)), None)


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

CLAUDE_ROOT = os.path.join(AGENT_SYNC_ROOT, "claude")
ARCHIVE = os.path.join(AGENT_SYNC_ROOT, "setup/logs/conflict-archive")
CLAUDE_BIN = find_claude_bin()

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

# ---------------------------------------------------------------------------
# Pass 4: dream pass (memory curation), main machine only, runs after pass 3.
# For each memory/<project>/ (including _global/) a headless Claude call
# curates that one directory in place. See module docstring for the full
# behavior. Every directory is archived before the call and restored verbatim
# if the call fails or the result doesn't pass the post-guards.
# ---------------------------------------------------------------------------
DREAM_ARCHIVE = os.path.join(AGENT_SYNC_ROOT, "setup/logs/dream-archive")
DREAM_STATE_FILE = os.path.join(AGENT_SYNC_ROOT, "setup/logs/dream-state.json")

DREAM_PROMPT = """You are running the nightly "dream pass" — memory curation — for a \
Claude Code persistent memory store rooted at the current working directory ("memory/"). \
Each subdirectory of memory/ is a project's memory (one file per fact); "_global/GLOBAL.md" \
holds facts that apply across every project (user traits, cross-project workflow feedback) \
instead of one-file-per-fact.

A memory file looks like:

---
name: <short-kebab-case-slug>
description: <one-line summary — used to decide relevance during recall>
metadata:
  type: user | feedback | project | reference
---

<the fact; for feedback/project, followed by **Why:** and **How to apply:** lines>

Your task is scoped STRICTLY to the subdirectory "{name}" and the file "_global/GLOBAL.md". \
Do not read, list, or modify anything else under memory/ — no other project subdirectory, \
no other file under _global/.

Do the following, using the Read, Write, Edit, Glob, and Grep tools directly (don't just \
describe the changes):

1. Merge duplicate or near-duplicate memory files in "{name}" so each remaining file holds \
one fact. Where two files disagree, keep the newer/more specific fact; never invent facts \
that aren't already supported by the existing text.
2. For every "<stem>-alt-N.md" file in "{name}" (a sync-conflict review copy of \
"<stem>.md"), fold anything genuinely new it contains into the base "<stem>.md" file, then \
delete the "-alt-N.md" file.
3. Convert relative dates ("yesterday", "last week", "2 days ago", etc.) to absolute dates \
(today is {today}). Prune only entries that are clearly stale — completed or discarded \
work with no future reference value — and be conservative: keep anything you're unsure \
about.
4. If "{name}" is a project directory (not "_global" itself): move any fact that is \
actually project-agnostic (a user trait/preference, or workflow feedback that applies \
across all projects, not just "{name}") into the appropriate section of \
"_global/GLOBAL.md", then remove it from "{name}" (delete the file, or the fact plus its \
MEMORY.md line, as appropriate). If "{name}" IS "_global", skip this step — only merge \
duplicate/contradictory content within GLOBAL.md itself.
5. If "{name}" is a project directory: rebuild "{name}/MEMORY.md" so it has exactly one \
line per remaining memory file, in the form "- [Title](file.md) — hook", stays under 200 \
lines, and has no link to a file that no longer exists. "_global" has no MEMORY.md — skip \
this step for it.

When finished, reply with a one-line summary of what you changed."""


def load_dream_state():
    try:
        with open(DREAM_STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_dream_state(state):
    os.makedirs(os.path.dirname(DREAM_STATE_FILE), exist_ok=True)
    with open(DREAM_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def dir_md_files(d):
    return glob.glob(os.path.join(d, "*.md"))


def dir_latest_mtime(d):
    files = [f for f in glob.glob(os.path.join(d, "*")) if os.path.isfile(f)]
    return max((os.path.getmtime(f) for f in files), default=None)


def dream_post_guard_failure(d, name, pre_md_count, pre_global_lines=None, global_md_path=None):
    """Return a failure reason string, or None if D passes all post-guards."""
    if name == "_global":
        global_md = os.path.join(d, "GLOBAL.md")
        if not os.path.exists(global_md) or os.path.getsize(global_md) == 0:
            return "GLOBAL.md missing or empty"
    else:
        index = os.path.join(d, "MEMORY.md")
        if not os.path.exists(index) or os.path.getsize(index) == 0:
            return "MEMORY.md missing or empty"
        with open(index) as f:
            index_lines = f.read().splitlines()
        if len(index_lines) > 200:
            return f"MEMORY.md has {len(index_lines)} lines (> 200)"
        for line in index_lines:
            m = re.search(r"\]\(([^)]+)\)", line)
            if m and not os.path.exists(os.path.join(d, m.group(1))):
                return f"MEMORY.md links to missing file: {m.group(1)}"

        # Project runs may only grow _global/GLOBAL.md (fact promotion); any
        # shrinkage means the call touched it beyond its scope. pre_global_lines
        # is None when GLOBAL.md didn't exist pre-run -- nothing to guard then.
        if pre_global_lines is not None:
            if not os.path.exists(global_md_path) or os.path.getsize(global_md_path) == 0:
                return "GLOBAL.md missing or empty after project run"
            with open(global_md_path) as f:
                post_global_lines = len(f.read().splitlines())
            if post_global_lines < pre_global_lines:
                return (f"GLOBAL.md shrank from {pre_global_lines} to "
                        f"{post_global_lines} lines during project run")

    post_md_count = len(dir_md_files(d))
    if post_md_count < pre_md_count * 0.5:
        return f".md file count dropped from {pre_md_count} to {post_md_count}"
    return None


def run_dream_pass(d, dream_state):
    name = os.path.basename(d)
    is_project = name != "_global"
    global_md_path = os.path.join(ROOT, "_global", "GLOBAL.md")

    if os.path.exists(os.path.join(d, ".consolidate-lock")):
        LOG.append(f"dream: skipped {name} (auto-dream lock present)")
        return

    latest_mtime = dir_latest_mtime(d)
    if latest_mtime is None:
        LOG.append(f"dream: skipped {name} (no files)")
        return

    last_run = dream_state.get(name)
    if last_run:
        try:
            last_run_ts = datetime.fromisoformat(last_run).timestamp()
        except ValueError:
            last_run_ts = None
        if last_run_ts is not None and latest_mtime <= last_run_ts:
            LOG.append(f"dream: skipped {name} (no changes since last dream run)")
            return

    pre_md_count = len(dir_md_files(d))
    # Collision-suffix the stamp if it's already taken (e.g. a manual re-run
    # of the whole script within the same second) -- copytree below requires
    # the destination not exist, and archive dirs are otherwise never cleaned.
    base_stamp = time.strftime("%Y%m%d-%H%M%S")
    stamp = base_stamp
    n = 1
    while os.path.exists(os.path.join(DREAM_ARCHIVE, stamp, name)):
        n += 1
        stamp = f"{base_stamp}-{n}"
    archive_dir = os.path.join(DREAM_ARCHIVE, stamp, name)
    os.makedirs(os.path.dirname(archive_dir), exist_ok=True)
    shutil.copytree(d, archive_dir)

    # Project runs are allowed to touch one file outside their own directory --
    # _global/GLOBAL.md, for fact promotion -- so archive it too and restore it
    # atomically with the project dir. Skip gracefully if it doesn't exist yet.
    pre_global_lines = None
    global_archive = None
    if is_project and os.path.exists(global_md_path):
        global_archive_dir = os.path.join(DREAM_ARCHIVE, stamp, "_global")
        os.makedirs(global_archive_dir, exist_ok=True)
        global_archive = os.path.join(global_archive_dir, "GLOBAL.md")
        shutil.copy2(global_md_path, global_archive)
        with open(global_md_path) as f:
            pre_global_lines = len(f.read().splitlines())

    def restore():
        shutil.rmtree(d)
        shutil.copytree(archive_dir, d)
        if global_archive:
            shutil.copy2(global_archive, global_md_path)

    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", "sonnet",
             "--permission-mode", "acceptEdits",
             "--allowedTools", "Read,Write,Edit,Glob,Grep"],
            input=DREAM_PROMPT.format(name=name, today=time.strftime("%Y-%m-%d")),
            cwd=ROOT, capture_output=True, text=True, timeout=900)
    except Exception as exc:
        LOG.append(f"dream: {name} subprocess error ({exc}); restored from archive")
        restore()
        return

    if result.returncode != 0:
        LOG.append(f"dream: {name} claude exited {result.returncode}; restored from archive")
        restore()
        return

    failure = dream_post_guard_failure(d, name, pre_md_count, pre_global_lines, global_md_path)
    if failure:
        LOG.append(f"dream: {name} post-guard failed ({failure}); restored from archive")
        restore()
        return

    dream_state[name] = datetime.now(timezone.utc).isoformat()
    save_dream_state(dream_state)
    LOG.append(f"dream: curated {name}")


if CLAUDE_BIN is None:
    LOG.append("dream: skipped entirely (no claude binary found)")
else:
    _dream_state = load_dream_state()
    for _dream_dir in sorted(glob.glob(os.path.join(ROOT, "*"))):
        if os.path.isdir(_dream_dir):
            run_dream_pass(_dream_dir, _dream_state)

print("\n".join(LOG) if LOG else "no conflicts")
