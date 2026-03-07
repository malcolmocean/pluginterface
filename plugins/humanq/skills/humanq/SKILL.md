---
name: humanq
description: Use when you need a human to do something you can't - register an OAuth client, click a button in a web UI, approve something, provide a secret, etc. Creates a task in Roam Research for the human to action.
---

# HumanQ - Queue a task for the human

When you're blocked on something only a human can do, use this skill to create a task in Roam Research.

## Prerequisites

The user must have run `/humanq:setup` to configure their Roam graph, API token, and target page UID. Config lives in `~/.config/pluginterface/humanq/`.

## When to use

- Registering OAuth clients / API credentials in a web console
- Approving something in a UI you can't access
- Providing secrets, passwords, or tokens
- Any action that requires a browser/GUI you don't have access to
- Physical-world actions
- Multi-step manual procedures (DNS setup, OAuth config, etc.)

## How to post

Single command — pass JSON as an argument to `post-task.py` located in the plugin directory (same directory as this skill's parent):

```bash
python3 <PLUGIN_DIR>/post-task.py '<JSON>'
```

Where `<PLUGIN_DIR>` is the directory containing `post-task.py`. Find it relative to this skill file — it's two levels up from this SKILL.md (i.e., the `humanq` plugin root). You can locate it with:

```bash
HUMANQ_DIR="$(dirname "$(dirname "$(find ~/.claude/skills ~/.claude/plugins -name 'post-task.py' -path '*/humanq/*' 2>/dev/null | head -1)")" 2>/dev/null)"
```

Or just use the known path if installed via pluginterface: the post-task.py will be in the same directory tree as this skill.

### JSON format

```json
{
  "title": "Short task description",
  "project": "project-name",
  "why": "Context about what you're doing and why this is needed",
  "provide_back": "What info you need returned, e.g. client ID and secret",
  "notes": "Any caveats, timing, gotchas",
  "steps": [
    {
      "text": "Step 1: Do the first thing",
      "details": ["detail line 1", "detail line 2"]
    },
    {
      "text": "Step 2: Do the next thing",
      "details": ["`command or code`"]
    }
  ]
}
```

- **title** (required): Clear one-line description of what you need
- **project** (optional): Defaults to current directory name
- **why** (optional): Context block
- **steps** (optional): Each becomes a nested `{{[[TODO]]}}` the human can check off individually. Each step can have `details` (child blocks with instructions, commands, etc.)
- **provide_back** (optional): What info you need returned
- **notes** (optional): Caveats, timing, gotchas

For simple single-action tasks, omit `steps` entirely.

The script handles: UID generation, date tagging (Roam format), project tagging, block creation, and tracking in `~/.config/pluginterface/humanq/tasks.json`.

### Output

Returns JSON: `{"uid": "hq_...", "status": "posted"}`

### Example: Simple task

```bash
python3 <PLUGIN_DIR>/post-task.py '{
  "title": "Register OAuth client for Slapture",
  "project": "slapture",
  "why": "Need Google Sheets API access for spreadsheet discovery",
  "provide_back": "Client ID and Client Secret",
  "notes": "Make sure the Sheets API is enabled in the same project"
}'
```

### Example: Multi-step task

```bash
python3 <PLUGIN_DIR>/post-task.py '{
  "title": "DNS setup for slapture.com → Cloud Run",
  "project": "slapture",
  "why": "Need to map custom domain to the deployed Cloud Run service",
  "steps": [
    {"text": "1. Get Cloud Run service URL", "details": ["Note the auto-assigned URL after deploying"]},
    {"text": "2. Map custom domain in Cloud Run", "details": [
      "`gcloud run domain-mappings create --service slapture --domain slapture.com --region us-east1`",
      "`gcloud run domain-mappings create --service slapture --domain www.slapture.com --region us-east1`"
    ]},
    {"text": "3. Set DNS records at registrar", "details": [
      "Cloud Run will output A, AAAA, and CNAME records to create",
      "Usually 4 A + 4 AAAA + 1 CNAME (www → ghs.googlehosted.com)"
    ]},
    {"text": "4. Wait for SSL (15-30 min)", "details": [
      "Check: `gcloud run domain-mappings describe --domain slapture.com --region us-east1`"
    ]},
    {"text": "5. Verify", "details": [
      "https://slapture.com loads",
      "https://www.slapture.com loads",
      "http:// redirects to https://"
    ]}
  ],
  "notes": "DNS propagation can take up to 48h but usually 5-30 min"
}'
```

## After posting

Tell the user:
- What you posted and why
- That it's on their HumanQ page in Roam
- What info you need back (if any) to continue

## Checking if a task you posted is done

If you posted a HumanQ task **in this session** and you later need the result to continue, check Roam:

```bash
<PLUGIN_DIR>/roam.sh q "{
  \"query\": \"[:find ?s :where [?e :block/uid \\\"<BLOCK_UID>\\\"] [?e :block/string ?s]]\"
}"
```

- If the string starts with `{{[[DONE]]}}`, read child blocks for any info the human left, and update `~/.config/pluginterface/humanq/tasks.json` status to `"completed"`.
- If still `{{[[TODO]]}}`, tell the user you're blocked on it and move on.

To read child blocks (e.g., credentials the human pasted):
```bash
<PLUGIN_DIR>/roam.sh q "{
  \"query\": \"[:find ?child-str :where [?e :block/uid \\\"<BLOCK_UID>\\\"] [?e :block/children ?c] [?c :block/string ?child-str]]\"
}"
```

Only check when you actually need the result. Don't check speculatively.

## Important notes

- Always include enough context that the human can act without asking follow-up questions
- If you need info back, be explicit about what format/values you need
- Don't create duplicate tasks — check `~/.config/pluginterface/humanq/tasks.json` first
- For tasks with 5+ steps, always use nested TODOs (steps)
- Roam supports `**bold**`, `` `code` ``, triple-backtick code blocks, and `[[page refs]]`
