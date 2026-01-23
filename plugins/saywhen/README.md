# SayWhen

A Claude Code plugin that provides voice notifications using macOS text-to-speech. Get audio alerts when Claude Code needs your attention.

## What it does

Announces out loud when:
- **"[project] blocked"** - Claude needs permission to proceed
- **"[project] complete"** - Task finished
- **"[project] idle"** - Claude is waiting
- **"[project] user input needed"** - Claude is asking a question

## Installation

### Option 1: Install from local path

```bash
# In Claude Code, run:
/plugin marketplace add /path/to/saywhen
/plugin install saywhen
```

### Option 2: Test locally without installing

```bash
claude --plugin-dir /path/to/saywhen
```

### Option 3: If hosted on GitHub

```bash
/plugin marketplace add your-username/saywhen
/plugin install saywhen
```

## Muting

Create `~/CC_MUTE.txt` to mute all notifications:

```bash
touch ~/CC_MUTE.txt   # mute
rm ~/CC_MUTE.txt      # unmute
```

## Configuration

The plugin extracts project names from paths by stripping everything up to `/dev/`. For example:
- `/Users/you/dev/myproject` announces as "myproject"
- `/Users/you/dev/projectA/feature-branch` announces as "projectA/feature-branch"

To customize the path pattern, edit `hooks/hooks.json` and change the `sed` command.

## Requirements

- macOS (uses the `say` command)
- Claude Code

## TODO

- [ ] Support muting specific event types
- [ ] Add a `/mute` command for easier control
