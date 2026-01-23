---
description: Configure saywhen project folder prefix for voice notifications
disable-model-invocation: true
---

# SayWhen Setup

Configure the parent folder prefix for path stripping in voice notifications.

## What This Does

When SayWhen announces project names, it strips the path up to your development folder. For example:
- If prefix is `dev`: `/Users/you/dev/myproject` announces as "myproject"
- If prefix is `code`: `/Users/you/code/myproject` announces as "myproject"
- If prefix is your username: `/Users/you/myproject` announces as "myproject"

## Steps

1. Ask the user what their parent development folder is (e.g., `dev`, `code`, or their username for home folder)

2. Run this command with their answer:

```bash
mkdir -p ~/.config/pluginterface/saywhen && echo "PREFIX_HERE" > ~/.config/pluginterface/saywhen/prefix
```

Replace `PREFIX_HERE` with the folder name they provided (just the name, not the full path).

3. Confirm the setup is complete and explain they can re-run `/saywhen:setup` to change it later.
