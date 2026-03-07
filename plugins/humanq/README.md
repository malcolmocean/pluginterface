# HumanQ

A Claude Code plugin that lets AI instances queue tasks for you in Roam Research. When Claude Code is blocked on something only a human can do — registering an OAuth client, setting up DNS, providing a secret — it posts a structured TODO to your Roam graph.

## What it does

- Posts `{{[[TODO]]}}` blocks to a designated Roam Research page
- Supports nested TODOs for multi-step tasks (DNS setup, OAuth config, etc.)
- Tags tasks with date and project for filtering
- Tracks posted tasks locally so the AI can check if they've been completed
- The AI can read back info you leave in Roam (credentials, URLs, etc.)

## Requirements

- [Roam Research](https://roamresearch.com/) account with API access
- Roam API token (Settings > Graph > API Tokens)
- A page in Roam to receive tasks (e.g. "HumanQ")
- Python 3 and curl

## Setup

```
/humanq:setup
```

You'll need:
1. Your Roam graph name
2. A Roam API token
3. The UID of your target page

## How it works

When Claude Code encounters something it can't do, it invokes the humanq skill and posts a task like:

```
{{[[TODO]]}} Register OAuth client for MyApp — [[myapp]] — [[March 6th, 2026]]
├── **Why:** Need Google Sheets API access for spreadsheet discovery
├── {{[[TODO]]}} 1. Go to Google Cloud Console > Credentials
│   └── Create OAuth 2.0 Client ID, type: Web Application
├── {{[[TODO]]}} 2. Set redirect URI
│   └── `https://myapp.com/auth/callback`
├── **Provide back:** Client ID and Client Secret
└── **Notes:** Sheets API must be enabled in the same project
```

You check off the steps in Roam, paste any requested info as child blocks, and the AI can query for the result.
