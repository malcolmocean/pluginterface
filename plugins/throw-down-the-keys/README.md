# throw-down-the-keys

Borrow auth state from a one-time browser login so an unattended CLI or remote agent can
stay logged in to a web app indefinitely.

## What it does

Most SaaS web apps issue short-lived bearer tokens (often 4h JWTs) and silently refresh
them in the background using a long-lived refresh token stored in the browser. If you
want a script or cloud agent to use the same API, you need to know:

1. Which endpoint the SPA hits to refresh
2. What it sends (refresh token in a body field? a cookie? a header?)
3. What it gets back (where in the JSON is the new bearer? does the refresh token rotate?)
4. The bootstrap credentials to start with

This plugin figures all of that out by launching a Chromium that you log into once, then
faking a 401 inside the browser so the SPA's interceptor fires its refresh flow — which
the plugin captures and analyzes.

## Install

```bash
/plugin install throw-down-the-keys
```

First-time setup (one-time, ~80 MB browser download):

```bash
uv run --with playwright playwright install chromium
```

## Use

```bash
/throw-down-the-keys https://www.example.com
```

A browser window opens. Log in normally. The plugin detects login automatically (polls
storage for a JWT-shaped or long opaque value), then drives the page to capture the
refresh round-trip.

When done, you'll have at `~/.config/throw-down-the-keys/example.com/`:

- `findings.md` — endpoint, request/response shape, JSON paths to the new tokens
- `how-to-wire-this-in.md` — language-agnostic implementation guide (file lock, atomic
  env write, single-writer-cron alternative)
- `.env` — `EXAMPLE_AUTH_TOKEN` + `EXAMPLE_REFRESH_TOKEN`, ready to copy to your agent
- `findings.json` — same as findings.md, machine-parseable
- `raw-capture.log` — full network log (treat as sensitive)

## Repeated runs

The browser profile is persisted per host at
`~/.config/throw-down-the-keys/profiles/<host>/`. Re-running on the same host skips the
login step entirely — the script just relaunches the already-logged-in Chromium and
re-captures.

## What this plugin does NOT do

- Doesn't write code into your project. The implementation guide is language-agnostic
  pseudocode + a checklist. Hand it (and `findings.md`) to a follow-up Claude prompt that
  knows your stack and have that prompt scaffold idiomatic refresh code.
- Doesn't automate login. You log in yourself, once.
- Doesn't keep refreshing in the background. Once the shape is captured, the plugin
  exits. Your CLI/agent does the refreshing using the guide.
