# agent-sync

**English** · [한국어](README.ko.md)

Run LLM CLI agents (Claude Code, Codex) on more than one computer and each
machine accumulates its own memory and settings. agent-sync gathers all of it
into a single `~/agent-sync` folder and syncs it across every machine in real
time — **whichever machine you work on, your agent runs with the same memory
and the same configuration.**

- **P2P, LAN-only** — sync is handled by [Syncthing](https://syncthing.net).
  Your machines talk to each other directly over encrypted connections with no
  cloud server; external relays and global discovery are disabled, so files
  never leave your network. Every machine holds a full copy, so any machine
  can be offline.
- **Your agent installs it** — setup is delegated to the agent on each machine
  via instruction documents (`setup/HANDOFF-*.md`). The human's job is passing
  along a device ID and approving the macOS permission popup.
- **This repo is a skeleton** — scripts and shared config only. Memory contents
  and personal customizations (agent/skill definitions) are not in git, so
  cloning gives you an empty, independent cluster of your own machines.

## What gets synced

| Item | How |
|---|---|
| Per-project auto-memory | A SessionStart hook writes `autoMemoryDirectory` into each git repo's `.claude/settings.local.json` → every machine uses the same memory folder |
| Global memory | `~/.claude/CLAUDE.md` (symlink) imports `memory/_global/GLOBAL.md` → loaded into every session on every machine |
| Shared Claude Code settings | `claude/settings.base.json` is auto-merged into each machine's `~/.claude/settings.json` (machine-specific entries preserved) |
| Personal agents · skills · commands | `~/.claude/agents` etc. are symlinks — synced across machines, not distributed via git |
| Codex global instructions | `~/.codex/AGENTS.md` symlink — points Codex at the same memory folder |

Note: `autoMemoryDirectory` is ignored for security reasons when set in a
committed `.claude/settings.json`, so a hook generating `settings.local.json`
per machine is the only way this works. There is nothing to configure per
project or per machine.

## Quick start

### First machine (main role)

Tell the agent on that machine:

> **"Clone `https://github.com/hierrr/agent-sync.git` to `~/agent-sync`, read
> `setup/HANDOFF-main.md` and execute it."**

Once the agent finishes setup and verification, it reports this machine's
**device ID** and opens a **60-minute enrollment window** for new machines
(machines set up within this window are auto-accepted; it closes
automatically).

main is the cluster's single hub (it introduces new machines and runs nightly
maintenance). It is not the data origin — every machine keeps a full copy.

### Adding machines (sub role)

Tell the agent on each machine you add — with `<MAIN_ID>` replaced by the
device ID reported above:

> **"Read `~/agent-sync/setup/HANDOFF-sub.md` and execute it. The main ID is
> `<MAIN_ID>`."**

If the enrollment window is open, that's it — the machine is auto-accepted and
syncing starts within about a minute. If the window has closed, pass the
device ID reported by the sub agent to the main agent and have it accepted
(*"accept device `YYY`"*).

To run it yourself without an agent:

```bash
git clone https://github.com/hierrr/agent-sync.git ~/agent-sync
chmod +x ~/agent-sync/setup/setup-machine.sh
~/agent-sync/setup/setup-machine.sh --role main                  # first machine
~/agent-sync/setup/setup-machine.sh --role sub --main-id <ID>    # additional machines
~/agent-sync/setup/setup-machine.sh --accept <ID>                # accept later, on main
~/agent-sync/setup/setup-machine.sh --enroll [minutes]           # reopen enrollment window
```

## What the human does (complete list)

| When | Task |
|---|---|
| First machine (main) | Prompt the agent → **note the main ID** it reports |
| Adding machines (within 60 min of main setup) | Prompt each machine's agent (include the main ID) |
| Adding machines (later) | Same as above + **pass the sub's ID to the main agent** |
| During each machine's setup (all machines) | Click **Allow** on the macOS "Syncthing local network" popup (once per machine) |
| Anything else | Nothing — pairing, acceptance, and sync are fully automatic |

## How it works

- **Auto-memory wiring**: Claude Code's SessionStart hook
  (`claude/hooks/ensure-automemory.sh`) points each git repo's auto-memory at
  `~/agent-sync/memory/<repo-name>` whenever you open it. The repo's `.claude`
  is kept out of git via a local exclude.
- **Settings merge**: `setup/apply-settings.py` merges the shared
  `claude/settings.base.json` into each machine's `~/.claude/settings.json`.
  Machine-local entries such as permissions are preserved, and a watcher
  launchd re-applies automatically when the base changes.
- **Nightly maintenance** (main only, 4:30 AM): first merges Syncthing
  conflicts caused by two machines editing the same file at once — memory
  indexes as a union, agent/skill definitions via a headless LLM call
  (originals preserved in `setup/logs/conflict-archive/`) — then runs a
  **dream pass**: a headless LLM call curates each memory directory in place,
  merging duplicate or contradictory facts, folding conflict review copies
  back in, converting relative dates to absolute, promoting project-agnostic
  facts to `_global/GLOBAL.md`, and rebuilding each `MEMORY.md` index. Every
  directory (including `GLOBAL.md`) is archived to `setup/logs/dream-archive/`
  first and restored atomically if the run fails its sanity guards; unchanged
  directories are skipped. Also cleans up a stale-lock-file bug in Claude
  Code's built-in auto-dream.
- **Syncthing runs as the menu bar app**: on macOS 15+ the app is the only
  form that can be granted Local Network permission — a background service
  (brew services) can't receive it, and LAN traffic gets silently blocked.
  The `syncthing` command is provided as a symlink to the app's built-in CLI,
  and setup automatically cleans up an old brew package if present.
- **Security**: device authentication uses Syncthing certificate fingerprints
  (device IDs), and this repository contains no device information. While the
  60-minute enrollment window is open, any machine that knows main's device ID
  is auto-accepted — share the device ID only with machines you trust.

## Requirements

- macOS (for Windows, see the beta notes below)
- Claude Code CLI
- Homebrew (for automatic Syncthing install — manual install works too)

## Operations

- **Changing settings**: edit `claude/settings.base.json` → on save, Syncthing
  propagates it and each machine's watcher launchd merges it automatically.
- **Moving the main role**: run `--role main` on the new machine + unload the
  old main's `com.palusomni.agentsync.merge` launchd.
- **Git usage**: this repository is for distribution and sharing improvements.
  To pick up a change, pull once on any machine — file content reaches every
  other machine within seconds via Syncthing, and each machine's own git state
  aligns to it automatically (a post-merge hook broadcasts a sentinel that
  triggers a watcher on every machine, with a session-start check and the
  nightly job as fallbacks), so there's no manual `git reset` to run on the
  other machines. Still commit only from one managed machine, and only when
  you've improved the scripts.

## Troubleshooting

**Files don't show up on another machine** — check pairing. On any machine:

```bash
syncthing cli config devices list    # should list the other machines besides your own ID
syncthing cli config folders list    # should list the agent-sync folder
syncthing cli show connections       # should show entries with connected: true
```

- Device list is correct but `connected: false` persists: check that Syncthing
  is allowed under System Settings > Privacy & Security > **Local Network**,
  and that both machines are on the same LAN — sync is LAN-only, so without
  both of these no connection can be established.
- Device list is empty: check that you ran `--role sub --main-id <ID>` on the
  sub, and accept that machine on main (`--accept <sub's device ID>`). If
  needed, you can also operate manually at http://127.0.0.1:8384 (Syncthing
  GUI).

**A session sees stale memory** — memory is loaded at session start. Memory
just saved on another machine appears from the next session on.

**Undoing the setup** — restore from the backups the setup created:
`~/.claude/settings.json.pre-agent-sync.bak` (settings),
`~/.claude/*.premerge.bak` (pre-symlink originals).

## Windows support (beta)

There are no native scripts yet. For Windows machines we recommend
**delegating the install to that machine's agent** — shell and permission
environments vary too much, and an agent that can inspect the machine directly
is the safer operator.

Tell the agent: *"Read this README and the `setup/` sources, and using the
mapping table below, build the equivalent setup on this Windows machine and
verify each step."*

| macOS component | Windows equivalent |
|---|---|
| `setup-machine.sh` (bash) | Equivalent logic in PowerShell |
| launchd (watcher / nightly job) | Task Scheduler |
| Syncthing menu bar app | winget / manual install (SyncTrayzor etc.) |
| `~/.claude/*` symlinks | Enable Developer Mode, then symlinks (or junctions) |
| SessionStart hook (bash+python3) | Git Bash recommended (otherwise the hook runs under PowerShell — needs porting) |
| Path `~/agent-sync` | `%USERPROFILE%\agent-sync` (Claude Code expands `~/` on any OS) |

It's a beta: after building it, make sure every verification item in the
HANDOFF documents passes.

## Folder layout

```
~/agent-sync/
├── memory/                    # auto-memory (Syncthing-only, not in git)
│   ├── _global/GLOBAL.md      #   global memory — loaded into every session
│   └── <repo-name>/           #   per-project memory — wired up by the hook
├── claude/
│   ├── CLAUDE.md              # global instructions (symlink target of ~/.claude/CLAUDE.md)
│   ├── agents|skills|commands/  # personal customizations (Syncthing-only, not in git)
│   ├── hooks/ensure-automemory.sh
│   └── settings.base.json     # shared settings (SessionStart hook, autoDreamEnabled, ...)
├── codex/AGENTS.md            # Codex global instructions
└── setup/                     # setup scripts, launchd definitions, agent handoff docs
```

## License

[MIT](LICENSE)
