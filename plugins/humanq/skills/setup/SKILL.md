---
name: setup
description: Configure HumanQ - set up Roam Research graph, API token, and target page for task queuing
---

# HumanQ Setup

Configure the Roam Research connection so Claude Code can post tasks for you.

## Steps

1. Ask the user for their **Roam graph name** (the name shown in Roam's graph selector)

2. Ask for their **Roam API token** (Settings > Graph > API Tokens in Roam)

3. Ask for their **target page UID** — this is the Roam page where tasks will be posted. They should:
   - Create a page in Roam (e.g. "HumanQ")
   - Right-click the page title > "Copy block reference"
   - The UID is the part inside `(())`

4. Save the config:

```bash
mkdir -p ~/.config/pluginterface/humanq && echo "<GRAPH_NAME>" > ~/.config/pluginterface/humanq/graph && echo "<API_TOKEN>" > ~/.config/pluginterface/humanq/token && echo "<PAGE_UID>" > ~/.config/pluginterface/humanq/page_uid
```

5. Confirm setup is complete. They can re-run `/humanq:setup` to change settings later.
