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

## Setup

After installing, configure your project folder prefix:

```
/saywhen:setup
```

This tells SayWhen how to extract project names from paths. For example:
- If your projects are in `~/dev/`, enter `dev`
- If your projects are in `~/code/`, enter `code`
- If your projects are directly in your home folder, enter your username

You can also run the setup script directly:

```bash
bash /path/to/saywhen/setup.sh
```

## Commands

- `/saywhen:setup` - Configure the project folder prefix
- `/saywhen:mute` - Mute voice notifications
- `/saywhen:unmute` - Unmute voice notifications

## Configuration

Configuration is stored in `~/.config/pluginterface/saywhen/`:
- `prefix` - The folder name used to extract project names from paths
- `mute` - If this file exists, notifications are muted

### How path extraction works

The plugin strips the path up to your configured prefix. For example, with prefix `dev`:
- `/Users/you/dev/myproject` announces as "myproject"
- `/Users/you/dev/projectA/feature-branch` announces as "projectA/feature-branch"

If no prefix is configured, it falls back to using the current directory name.

## Requirements

- macOS (uses the `say` command)
- Claude Code

## Testing

Run the test suite:

```bash
cd /path/to/saywhen
bash test/setup_test.sh
bash test/hooks_test.sh
```
