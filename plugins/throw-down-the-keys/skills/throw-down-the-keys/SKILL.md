---
name: throw-down-the-keys
description: Use when the user wants a CLI or remote agent to stay authenticated to a web app indefinitely - borrows auth state from a one-time browser login, finds the SPA's silent-refresh endpoint by faking a 401 inside Playwright, then writes bootstrap credentials plus a language-agnostic implementation guide. Run as `/throw-down-the-keys <url>`.
---

# throw-down-the-keys

Drives `/Users/malcolm/dev/pluginterface/plugins/throw-down-the-keys/throw_down.py`.
The script launches a headed Chromium with a per-host persisted profile, waits for the
user to log in once (ever — the profile is kept), then drives the page to discover and
capture the SPA's silent token-refresh endpoint.

## When to use

- The user wants an unattended client (cloud agent, cron job, local CLI) to stay logged in
  to a SaaS web app whose login is gated by reCAPTCHA / SSO / 2FA and so can't be scripted.
- The web app uses short-lived bearer tokens (JWTs or opaque) that refresh silently in the
  background while the user is on the site.
- Phrases that should trigger this: "stay logged in", "auto-refresh tokens", "agent keeps
  getting 401s", "find the refresh endpoint", "borrow my browser session".

## When NOT to use

- The site offers a documented API + a personal access token / long-lived API key. Just
  have the user generate one of those.
- The user wants programmatic *login* (username/password). This skill assumes the user can
  log in via the browser themselves. It does not automate the login itself.

## Prerequisites — confirm before first run

- Playwright Chromium installed: `uv run --with playwright playwright install chromium`
- macOS / Linux (uses `fcntl` for file locks; will explain the equivalent for Windows in
  the generated guide but doesn't generate Windows code).

## How to run

Pass the target URL as the only argument:

```bash
uv --project /Users/malcolm/dev/pluginterface/plugins/throw-down-the-keys \
   run --with playwright --with httpx \
   python /Users/malcolm/dev/pluginterface/plugins/throw-down-the-keys/throw_down.py \
   https://www.example.com
```

You can also pass `--login-timeout-min N` (default 10) if the user needs longer.

## What happens

1. A Chromium window opens for the target URL.
2. **First run**: the user logs in normally (filling reCAPTCHA, 2FA, whatever). The script
   polls localStorage / sessionStorage every 1s for a JWT-shaped value or any long opaque
   token, and prints "Login detected" once it sees one. The browser profile is persisted
   at `~/.config/throw-down-the-keys/profiles/<host>/`, so subsequent runs skip this step
   entirely.
3. The script captures a full network log, then arms a Playwright route handler that
   transparently rewrites the next plausible API GET to a 401 response. The SPA sees the
   401 and fires its refresh handler.
4. The script identifies the refresh request, decodes the JWT for lifetime, locates the
   new tokens in the response.
5. Writes artifacts to `~/.config/throw-down-the-keys/<host>/`:
   - `findings.md` — endpoint URL, request shape, response shape, JSON paths to new
     tokens, JWT decode, storage scan
   - `how-to-wire-this-in.md` — language-agnostic refresh-on-401 implementation guide
     (file lock, atomic env write, single-writer-cron alternative, when to re-bootstrap)
   - `.env` — bootstrap credentials as `<HOST>_AUTH_TOKEN` + `<HOST>_REFRESH_TOKEN`
   - `findings.json` — structured form of findings.md for programmatic consumption
   - `raw-capture.log` — full network log (sensitive tokens partially redacted in
     headers but bodies are not — treat the file as a credential)

The script exits when done. Browser closes automatically.

## After the script returns

You (Claude or the user) should:

1. Read `findings.md` to confirm the endpoint was identified correctly. If it shows
   `NOT FOUND`, scan `raw-capture.log` for `>>> FAKED 401` and see what request fired
   right after.
2. Hand `findings.md` + `how-to-wire-this-in.md` to a follow-up Claude prompt that knows
   the user's stack (Python? Node? Go?) and have it implement the auto-refresh module
   in that codebase, then a CLI subcommand or daemon to do the actual refresh.
3. Copy `.env` (or its values) to the agent/CLI that needs to stay authenticated.

## Limitations to flag if the user asks

- One refresh round-trip is captured. If the site does multi-step refresh (e.g., trade
  RT for an auth code, then code for a JWT), only the first step is recognized.
- Cookie-only refresh (no JSON body) works — the captured request will show `cookies:
  true` and the response Set-Cookie list. The implementation guide handles this case.
- CSRF tokens / device-fingerprint headers will appear in the captured request headers
  and need to be replayed; the guide mentions this but the user has to wire it through.

## Where the user's session lives

Per-host browser profiles at `~/.config/throw-down-the-keys/profiles/<host>/`. Deleting
that directory means the user has to log in again. Artifacts at
`~/.config/throw-down-the-keys/<host>/` are independent — if the bootstrap creds in
`.env` are still valid (i.e., the refresh token's server TTL hasn't expired), the user
can also use those to bootstrap a fresh capture without re-login by manually injecting
them into the new Chromium profile.
