"""throw-down-the-keys — borrow a logged-in browser session to find a SPA's
silent-refresh endpoint, extract bootstrap credentials, and write an
implementation guide so an unattended CLI/agent can stay authenticated.

Usage:
    uv run --with playwright --with httpx python throw_down.py <url>
    uv run --with playwright playwright install chromium  # first time only

Persists a per-host Chromium profile so the user logs in once, ever.

Artifacts land in ~/.config/throw-down-the-keys/<host>/:
    findings.md             — endpoint URL, request/response shape, token paths
    how-to-wire-this-in.md  — language-agnostic refresh-on-401 implementation guide
    .env                    — bootstrapped <HOST>_AUTH_TOKEN + <HOST>_REFRESH_TOKEN
    raw-capture.log         — full network log for debugging
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Error as PWError, Page, Request, Response, Route, sync_playwright

CONFIG_ROOT = Path.home() / ".config" / "throw-down-the-keys"

BORING = re.compile(
    r"(/track/|/analytics/|/collect|/ccm/|/rum\?|googletag|doubleclick|googleadservices|"
    r"\.(png|jpg|jpeg|gif|svg|ico|woff2?|css|js|map)(\?|$))",
    re.I,
)
AUTH_HINT = re.compile(r"(refresh|token|auth|jwt|login|session|oauth)", re.I)
JWT_RE = re.compile(r"^eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+$")
JWT_VALUE_RE = re.compile(r"eyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]+")
OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,}$")


# --- data classes ---


@dataclass
class CapturedRequest:
    seq: int
    method: str
    url: str
    has_auth_header: bool
    headers: dict[str, str]
    body: str | None


@dataclass
class CapturedResponse:
    seq: int
    status: int
    method: str
    url: str
    set_cookie_names: list[str]
    body_json: Any | None
    body_text_preview: str | None


@dataclass
class Findings:
    target_url: str
    host: str
    refresh_endpoint: str | None = None
    refresh_method: str | None = None
    refresh_request_body: dict | str | None = None
    refresh_response_body: dict | None = None
    refresh_response_set_cookies: list[str] = field(default_factory=list)
    refresh_uses_authorization_header: bool = False
    refresh_uses_cookies: bool = False
    refresh_request_carries_refresh_token: bool = False
    storage_jwt_keys: list[dict] = field(default_factory=list)
    storage_opaque_keys: list[dict] = field(default_factory=list)
    bearer_jwt_decoded: dict | None = None
    bearer_lifetime_seconds: int | None = None
    bootstrap_bearer: str | None = None
    bootstrap_refresh: str | None = None


# --- JWT decode (no signature verification) ---


def decode_jwt(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


# --- redaction ---


def redact(value: str) -> str:
    if not value:
        return value
    if len(value) > 24:
        return value[:8] + "…" + value[-6:]
    return "…"


# --- capture machinery ---


class Capture:
    def __init__(self, host: str, log_fh):
        self.host = host
        self.log_fh = log_fh
        self.seq = itertools.count(1)
        self.requests: dict[int, CapturedRequest] = {}
        self.responses: list[CapturedResponse] = []
        # Maps Playwright Request object id -> our seq, so on_response can correlate.
        self._req_to_seq: dict[int, int] = {}

    def _interesting(self, req: Request) -> bool:
        if self.host not in req.url:
            return False
        if BORING.search(req.url):
            return False
        return True

    def on_request(self, req: Request) -> None:
        if not self._interesting(req):
            return
        n = next(self.seq)
        self._req_to_seq[id(req)] = n
        headers = {}
        for k, v in req.headers.items():
            if k.lower() in ("authorization", "cookie", "x-csrf-token", "x-xsrf-token"):
                headers[k] = redact(v)
            else:
                headers[k] = v
        has_auth = "authorization" in {k.lower() for k in req.headers}
        body = req.post_data
        cr = CapturedRequest(
            seq=n, method=req.method, url=req.url, has_auth_header=has_auth,
            headers=headers, body=body[:4000] if body else None,
        )
        self.requests[n] = cr
        self._log(f"\n--- REQ #{n} ---\n{req.method} {req.url}  [auth={'Y' if has_auth else 'N'}]\n"
                  f"{json.dumps(headers, indent=2)}\n"
                  + (f"body: {cr.body}\n" if cr.body else ""))

    def on_response(self, resp: Response) -> None:
        if not self._interesting(resp.request):
            return
        n = self._req_to_seq.get(id(resp.request), 0)
        set_cookies = resp.headers.get("set-cookie", "")
        cookie_names = [c.split("=", 1)[0].strip() for c in set_cookies.split(",") if "=" in c]
        body_json: Any | None = None
        text_preview: str | None = None
        try:
            text = resp.text()
            if text:
                try:
                    body_json = json.loads(text)
                except json.JSONDecodeError:
                    text_preview = text[:1000]
        except Exception as e:
            text_preview = f"<read err: {e}>"
        cr = CapturedResponse(
            seq=n, status=resp.status, method=resp.request.method, url=resp.request.url,
            set_cookie_names=cookie_names, body_json=body_json, body_text_preview=text_preview,
        )
        self.responses.append(cr)
        dump = json.dumps(body_json, indent=2)[:2000] if body_json is not None else (text_preview or "")
        self._log(f"--- RESP #{n} ---\n{resp.status} {resp.request.method} {resp.request.url}\n"
                  + (f"Set-Cookie names: {cookie_names}\n" if cookie_names else "")
                  + (f"body: {dump}\n" if dump else ""))

    def _log(self, msg: str) -> None:
        self.log_fh.write(msg)
        self.log_fh.flush()


# --- login detection ---


def find_jwt_in_storage(page: Page) -> str | None:
    snippet = """
        () => {
            for (const store of [localStorage, sessionStorage]) {
                for (const k of Object.keys(store)) {
                    try {
                        const v = store.getItem(k);
                        if (typeof v === 'string' && /^eyJ[\\w-]+\\.eyJ[\\w-]+\\./.test(v)) return v;
                    } catch (e) {}
                }
            }
            return null;
        }
    """
    try:
        return page.evaluate(snippet)
    except Exception:
        return None


def find_opaque_token_in_storage(page: Page) -> bool:
    """Heuristic: any long opaque value in storage suggests post-login state."""
    snippet = """
        () => {
            for (const store of [localStorage, sessionStorage]) {
                for (const k of Object.keys(store)) {
                    try {
                        const v = store.getItem(k);
                        if (typeof v === 'string' && /^[A-Za-z0-9_-]{32,}$/.test(v)) return true;
                    } catch (e) {}
                }
            }
            return false;
        }
    """
    try:
        return bool(page.evaluate(snippet))
    except Exception:
        return False


_OVERLAY_JS = """
(msg) => {
    let el = document.getElementById('__tdtk_overlay__');
    if (!el) {
        el = document.createElement('div');
        el.id = '__tdtk_overlay__';
        el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;'
            + 'background:#fef3c7;color:#92400e;font:600 14px/1.4 ui-sans-serif,system-ui;'
            + 'padding:10px 16px;border-bottom:3px solid #f59e0b;'
            + 'box-shadow:0 2px 8px rgba(0,0,0,0.2);text-align:center;';
        (document.body || document.documentElement).appendChild(el);
    }
    el.textContent = msg;
}
"""


def banner(page: Page, msg: str) -> None:
    try:
        page.evaluate(_OVERLAY_JS, msg)
    except PWError:
        pass


def clear_banner(page: Page) -> None:
    try:
        page.evaluate("() => document.getElementById('__tdtk_overlay__')?.remove()")
    except PWError:
        pass


def wait_for_login(page: Page, timeout_min: int = 10) -> bool:
    """Poll storage for a JWT or long opaque token. Returns True if detected."""
    deadline = time.time() + timeout_min * 60
    msg = ("🔑 throw-down-the-keys: please log in normally. "
           "This window is automated — I'll detect login and continue. Do not close.")
    print(f">>> Waiting for login (poll every 1s, up to {timeout_min} min). "
          "Log in normally in the browser; I'll detect it automatically.")
    last_msg = 0
    while time.time() < deadline:
        if find_jwt_in_storage(page) or find_opaque_token_in_storage(page):
            print(">>> Login detected.")
            return True
        if time.time() - last_msg > 30:
            print(f"  ...still waiting ({int(deadline - time.time())}s remaining)")
            last_msg = time.time()
        # Re-apply the banner — SPA navigations often clear DOM mutations.
        banner(page, msg)
        try:
            page.wait_for_timeout(1000)
        except Exception:
            return False
    return False


# --- storage scan ---


def scan_storage(page: Page) -> tuple[list[dict], list[dict]]:
    """Returns (jwt_entries, opaque_entries) with key names, lengths, previews."""
    snippet = """
        () => {
            const out = {jwt: [], opaque: []};
            for (const [name, store] of [['localStorage', localStorage], ['sessionStorage', sessionStorage]]) {
                for (const k of Object.keys(store)) {
                    try {
                        const v = store.getItem(k);
                        if (typeof v !== 'string') continue;
                        const entry = {storage: name, key: k, len: v.length, preview: v.slice(0, 30)};
                        if (/^eyJ[\\w-]+\\.eyJ[\\w-]+\\./.test(v)) {
                            entry.value = v;  // need full JWT for decoding
                            out.jwt.push(entry);
                        } else if (/^[A-Za-z0-9_-]{32,}$/.test(v)) {
                            entry.value = v;
                            out.opaque.push(entry);
                        }
                    } catch (e) {}
                }
            }
            return out;
        }
    """
    try:
        result = page.evaluate(snippet)
        return result.get("jwt", []), result.get("opaque", [])
    except Exception:
        return [], []


# --- fake-401 to force refresh ---


def arm_fake_401(ctx: BrowserContext, host: str, log_fh) -> dict:
    """Fulfill the next plausible API GET with a 401 to make the SPA think its token expired.
    Returns the state dict {fired: bool, url: str|None} so the caller can inspect."""
    state = {"fired": False, "url": None}
    # Skip auth-related paths and obvious analytics.
    safe = re.compile(r"/(?!.*(refresh|auth|token|jwt|login|oauth|session))", re.I)

    def handler(route: Route, req: Request) -> None:
        if state["fired"]:
            route.continue_()
            return
        if host not in req.url or req.method != "GET" or BORING.search(req.url):
            route.continue_()
            return
        if not safe.search(urlparse(req.url).path):
            route.continue_()
            return
        # Must look like a real JSON-ish API call (avoid 401-ing the SPA shell HTML).
        # Page navigations have Accept: text/html,... — exclude those.
        accept = req.headers.get("accept", "")
        if "text/html" in accept or "application/json" not in accept:
            route.continue_()
            return
        state["fired"] = True
        state["url"] = req.url
        log_fh.write(f"\n>>> FAKED 401 on {req.url}\n")
        log_fh.flush()
        route.fulfill(
            status=401,
            headers={"content-type": "application/json"},
            body='{"errors":[{"code":"access.denied","message":"Faked by throw-down-the-keys"}]}',
        )

    ctx.route("**/*", handler)
    return state


# --- identifying the refresh request in the capture ---


def identify_refresh(capture: Capture, fake_401_state: dict, known_refresh_token: str | None = None) -> CapturedRequest | None:
    """Find the refresh request in the capture.

    Looks at ALL captured POST/PUT requests (not just post-401), since many SPAs refresh
    proactively or on page load — the refresh may have already fired before we armed the
    fake-401. The fake-401 is a fallback to provoke a refresh if no natural one happened.

    Heuristics (a request gets a score; highest wins):
      +3  body contains the refresh-token string we extracted from storage
      +2  URL path contains refresh|token|auth|jwt|session
      +1  no Authorization header (refresh requests typically don't carry one)
      +1  fires after the faked 401 (if any)
    """
    fake_seq = 0
    fake_url = fake_401_state.get("url")
    if fake_url:
        for req in capture.requests.values():
            if req.url == fake_url:
                fake_seq = req.seq
                break

    candidates = [
        r for r in capture.requests.values()
        if r.method in ("POST", "PUT") and not BORING.search(r.url)
    ]

    def score(r: CapturedRequest) -> int:
        s = 0
        body = r.body or ""
        if known_refresh_token and known_refresh_token in body:
            s += 3
        if AUTH_HINT.search(urlparse(r.url).path):
            s += 2
        if not r.has_auth_header:
            s += 1
        if fake_seq and r.seq > fake_seq:
            s += 1
        return s

    if not candidates:
        return None
    candidates.sort(key=lambda r: (-score(r), r.seq))
    best = candidates[0]
    # Require a meaningful match — score 0 means it was just a regular write.
    return best if score(best) >= 2 else None


# --- response analysis ---


def find_paths_to_values(obj: Any, prefix: str = "$") -> list[tuple[str, str]]:
    """Yield (json_path, string_value) for every string value in nested dicts/lists."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(find_paths_to_values(v, f"{prefix}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(find_paths_to_values(v, f"{prefix}[{i}]"))
    elif isinstance(obj, str):
        out.append((prefix, obj))
    return out


def locate_token_in_response(response_body: Any, *, prefer_jwt: bool, exclude: set[str] | None = None) -> tuple[str | None, str | None]:
    """Walk the response and return (json_path, value) for the most likely token."""
    if not isinstance(response_body, (dict, list)):
        return None, None
    exclude = exclude or set()
    candidates = [(p, v) for p, v in find_paths_to_values(response_body) if v not in exclude]
    if prefer_jwt:
        for p, v in candidates:
            if JWT_RE.match(v):
                return p, v
    # Fall back: longest opaque token.
    opaque = [(p, v) for p, v in candidates if OPAQUE_TOKEN_RE.match(v) and not JWT_RE.match(v)]
    opaque.sort(key=lambda kv: -len(kv[1]))
    if opaque:
        return opaque[0]
    return None, None


# --- runner ---


def run(target_url: str, login_timeout_min: int) -> Findings:
    parsed = urlparse(target_url)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit(f"invalid url: {target_url!r} (expected e.g. https://example.com)")
    host = parsed.netloc
    out_dir = CONFIG_ROOT / host
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = CONFIG_ROOT / "profiles" / host
    profile_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "raw-capture.log"
    log_fh = log_path.open("w")
    print(f">>> Profile:   {profile_dir}")
    print(f">>> Artifacts: {out_dir}")
    print(f">>> Raw log:   {log_path}")

    findings = Findings(target_url=target_url, host=host)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        capture = Capture(host, log_fh)
        ctx.on("request", capture.on_request)
        ctx.on("response", capture.on_response)
        try:
            _drive(ctx, target_url, findings, capture, login_timeout_min)
        except SystemExit:
            raise
        except Exception as e:
            print(f"!!! Driving errored: {type(e).__name__}: {e}")
            print(f"    Will write whatever was captured.")
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            log_fh.close()
    return findings


def _drive(ctx: BrowserContext, target_url: str, findings: Findings, capture: Capture, login_timeout_min: int) -> None:
    """The main driving loop, factored out so run() can always return partial findings."""
    host = findings.host
    page = ctx.new_page()
    page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

    # Already logged in? Check storage AND that the JWT isn't expired.
    already = False
    jwt = find_jwt_in_storage(page)
    if jwt:
        claims = decode_jwt(jwt) or {}
        exp = claims.get("exp")
        if exp and int(exp) < int(time.time()):
            print(f">>> Storage JWT exists but expired {int(time.time()) - int(exp)}s ago — needs fresh login.")
        else:
            already = True
    elif find_opaque_token_in_storage(page):
        already = True

    if already:
        print(">>> Already logged in (existing browser profile).")
    else:
        if not wait_for_login(page, timeout_min=login_timeout_min):
            print("!!! Login not detected within timeout. Exiting.")
            raise SystemExit(1)

    # Let the SPA settle after login.
    try:
        page.wait_for_timeout(2000)
    except PWError:
        return

    # Snapshot storage (the bootstrap creds).
    jwt_entries, opaque_entries = scan_storage(page)
    findings.storage_jwt_keys = [{k: v for k, v in e.items() if k != "value"} for e in jwt_entries]
    findings.storage_opaque_keys = [{k: v for k, v in e.items() if k != "value"} for e in opaque_entries]

    bearer = jwt_entries[0]["value"] if jwt_entries else None
    if bearer:
        findings.bootstrap_bearer = bearer
        decoded = decode_jwt(bearer)
        if decoded:
            findings.bearer_jwt_decoded = {k: v for k, v in decoded.items() if k != "data" or isinstance(v, dict)}
            if "exp" in decoded and "iat" in decoded:
                findings.bearer_lifetime_seconds = int(decoded["exp"]) - int(decoded["iat"])

    if opaque_entries:
        findings.bootstrap_refresh = opaque_entries[0]["value"]

    # Belt-and-suspenders trigger:
    #  (a) corrupt any JWT in storage so SPAs that re-read storage per request will 401 naturally
    #  (b) arm a fake-401 interceptor for SPAs that hold the bearer in memory
    # The next API call goes 401 either way, and the SPA's refresh handler fires.
    try:
        page.evaluate("""
            () => {
                for (const store of [localStorage, sessionStorage]) {
                    for (const k of Object.keys(store)) {
                        try {
                            const v = store.getItem(k);
                            if (typeof v === 'string' && /^eyJ[\\w-]+\\.eyJ[\\w-]+\\.[\\w-]+$/.test(v)) {
                                const parts = v.split('.');
                                store.setItem(k, parts[0] + '.' + parts[1] + '.CORRUPTED');
                            }
                        } catch (e) {}
                    }
                }
            }
        """)
        print(">>> Corrupted JWT(s) in storage to force a natural 401.")
    except PWError:
        pass

    print(">>> Arming fake-401 interceptor; navigating to provoke an API call...")
    fake_state = arm_fake_401(ctx, host, capture.log_fh)
    probe_paths = ["/app", "/dashboard", "/home", "/account", "/settings", "/inbox"]
    for p in probe_paths:
        if fake_state["fired"]:
            break
        try:
            page.goto(target_url.rstrip("/") + p, wait_until="domcontentloaded", timeout=15000)
            # If the SPA bounced us to a login URL, the session is dead — bail rather than probe more.
            if "/login" in page.url:
                print(f"  probe {p} bounced to {page.url} — SPA thinks we're logged out. "
                      "Storage tokens are stale; need fresh login.")
                break
            # Wait for networkidle (SPA finishes its API calls), or up to 15s. networkidle is best-effort.
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PWError:
                pass
            page.wait_for_timeout(3000)
        except PWError as e:
            print(f"  probe {p} skipped: {type(e).__name__}")
            if "closed" in str(e).lower():
                break

    if not fake_state["fired"]:
        print("!!! Couldn't trigger an API call automatically.")
    else:
        print(f">>> Triggered fake-401 on {fake_state['url']}; capturing refresh attempt...")

    # Identify the refresh request from the capture (scans all POSTs, not just post-401).
    refresh_req = identify_refresh(capture, fake_state, known_refresh_token=findings.bootstrap_refresh)
    if refresh_req:
        findings.refresh_endpoint = refresh_req.url
        findings.refresh_method = refresh_req.method
        findings.refresh_uses_authorization_header = refresh_req.has_auth_header
        findings.refresh_uses_cookies = "cookie" in {k.lower() for k in refresh_req.headers}
        body = refresh_req.body or ""
        if findings.bootstrap_refresh and findings.bootstrap_refresh in body:
            findings.refresh_request_carries_refresh_token = True
        try:
            findings.refresh_request_body = json.loads(body) if body else None
        except json.JSONDecodeError:
            findings.refresh_request_body = body
        matching = [r for r in capture.responses if r.seq == refresh_req.seq]
        if matching:
            findings.refresh_response_body = matching[0].body_json
            findings.refresh_response_set_cookies = matching[0].set_cookie_names


# --- report writers ---


def host_to_envvar(host: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", host.upper().replace("WWW.", "").split(".")[0])


def write_findings(out_dir: Path, f: Findings) -> Path:
    envprefix = host_to_envvar(f.host)
    bearer_path, _ = (None, None)
    refresh_path, _ = (None, None)
    if f.refresh_response_body is not None:
        bearer_path, _ = locate_token_in_response(f.refresh_response_body, prefer_jwt=True)
        # Exclude the bearer value from refresh-token search to avoid picking the same string twice.
        exclude = set()
        if bearer_path:
            for p, v in find_paths_to_values(f.refresh_response_body):
                if p == bearer_path:
                    exclude.add(v)
                    break
        refresh_path, _ = locate_token_in_response(f.refresh_response_body, prefer_jwt=False, exclude=exclude)

    lifetime = "unknown"
    if f.bearer_lifetime_seconds:
        lifetime = f"{f.bearer_lifetime_seconds} seconds = {f.bearer_lifetime_seconds / 3600:.2f} hours"

    md = f"""# Findings — {f.host}

Target: `{f.target_url}`

## Access token

- Storage location: see `storage_jwt_keys` below
- Lifetime: **{lifetime}** (from JWT exp/iat, no signature verification)
- Decoded JWT claims (sensitive fields elided):

```json
{json.dumps(f.bearer_jwt_decoded, indent=2) if f.bearer_jwt_decoded else "<no JWT decoded>"}
```

## Refresh endpoint

- **{f.refresh_method or '?'} `{f.refresh_endpoint or 'NOT FOUND'}`**
- Sends Authorization header: `{f.refresh_uses_authorization_header}`
- Sends Cookie header: `{f.refresh_uses_cookies}`
- Carries the refresh token in the request body: `{f.refresh_request_carries_refresh_token}`

### Request body (as captured)

```json
{json.dumps(f.refresh_request_body, indent=2) if f.refresh_request_body else "<no body>"}
```

### Response body

```json
{json.dumps(f.refresh_response_body, indent=2) if f.refresh_response_body else "<no body captured>"}
```

### Where to find the new tokens in the response

- New access token at JSON path: `{bearer_path or '<not located>'}`
- New refresh token at JSON path: `{refresh_path or '<not located>'}`

### Response sets cookies

`{f.refresh_response_set_cookies}`

## Browser storage at login time

### JWT-shaped entries (most likely the access token)

```json
{json.dumps(f.storage_jwt_keys, indent=2)}
```

### Opaque-token entries (most likely the refresh token + miscellaneous)

```json
{json.dumps(f.storage_opaque_keys, indent=2)}
```

## Bootstrap credentials

Written to `.env` in this directory as:

- `{envprefix}_AUTH_TOKEN` — your current 4h-ish JWT
- `{envprefix}_REFRESH_TOKEN` — the refresh token (rotates on every use if the response above includes a new one)

## Caveats

- This run captured a single refresh round-trip. If your SPA gates refresh behind extra checks
  (CSRF, device fingerprint, header X), they should appear in the request capture above — check
  the request headers in `raw-capture.log`.
- Refresh tokens often rotate. Whether they do is visible above — if the response contains a
  different opaque token than the request, treat it as one-time-use and persist the new one
  every time.
- If "Where to find the new tokens" shows `<not located>`, scan `raw-capture.log` for the
  actual response — the JWT is in there somewhere; heuristics just didn't recognize it.
"""
    p = out_dir / "findings.md"
    p.write_text(md)
    return p


def write_implementation_guide(out_dir: Path, f: Findings) -> Path:
    envprefix = host_to_envvar(f.host)
    bearer_var = f"{envprefix}_AUTH_TOKEN"
    refresh_var = f"{envprefix}_REFRESH_TOKEN"

    md = f"""# How to wire this in — {f.host}

Once you have the bootstrap creds, the goal is: your CLI/agent runs indefinitely without
re-login, transparently refreshing its bearer when it expires.

## The pattern (language-agnostic)

Your HTTP client wraps every request with this logic:

```
def request(method, url, **kwargs):
    response = http.send(method, url, headers={{Authorization: f"Bearer {{bearer}}"}}, **kwargs)
    if response.status != 401:
        return response

    # 401 means the bearer expired (or was revoked).
    with file_lock(env_path):           # serialize across processes
        disk_refresh = read_env(env_path).{refresh_var}
        if disk_refresh != current_refresh:
            # Another process refreshed while we were waiting; adopt their tokens.
            bearer, current_refresh = read_env(env_path).{bearer_var}, disk_refresh
        else:
            # Hit the refresh endpoint.
            new_bearer, new_refresh = refresh(current_refresh)
            atomic_write_env(env_path, {{{bearer_var}: new_bearer, {refresh_var}: new_refresh}})
            bearer, current_refresh = new_bearer, new_refresh

    # Retry once with the new bearer.
    return http.send(method, url, headers={{Authorization: f"Bearer {{bearer}}"}}, **kwargs)
```

The three primitives:

1. **`refresh(rt)`** — POSTs to the endpoint shown in `findings.md`, parses the response at the
   JSON paths shown there, returns `(new_bearer, new_refresh_or_same)`.
2. **`file_lock(path)`** — exclusive advisory lock (POSIX `fcntl.flock`, or your language's
   equivalent). Required so two processes hitting 401 at the same time don't both burn the
   refresh token.
3. **`atomic_write_env(path, kvs)`** — write to `<path>.tmp` then `rename()` to `path`.
   Preserves other env keys; readers never see a half-written file.

## Why a lock if there's also the "adopt their tokens" check?

The lock makes the read-modify-write of the env file atomic; the adopt step covers the case
where another process *finished* refreshing while we were *waiting* for the lock — we use
their result instead of burning the (now-stale) refresh token a second time.

## Single-writer alternative (cron)

If your refresh token rotates on every call and you have many concurrent CLI processes, even
the lock + adopt pattern is fiddly. The bulletproof alternative: a single cron job that runs
`refresh` every ~75% of the bearer's lifetime. All your CLI processes just read `.env` and
never refresh themselves. The cron job is the only writer; no contention possible.

Pros: simpler reasoning. Cons: requires cron and the bootstrap step to set it up.

## When to re-bootstrap

If `refresh()` itself returns 401, the refresh token is dead — server-side TTL ran out, you
logged out from a separate session, or the token got revoked. Your code should exit with a
clear error pointing the user back to `/throw-down-the-keys {f.target_url}` to re-login once.

## Idempotency hints

- Don't put the bearer in any process-environment variable that gets inherited by subprocesses
  *and* read on each subprocess start — they'll all read the stale value. Read from `.env`
  fresh per HTTP call.
- If you cache `bearer` in memory for the lifetime of one CLI invocation, that's fine — but
  re-read from disk after a 401 (in case the refresh happened in a sibling process).

## Endpoint summary (mirrored from findings.md)

- {f.refresh_method or '?'} `{f.refresh_endpoint or 'NOT FOUND'}`
- Bearer lifetime: ~{f.bearer_lifetime_seconds / 3600:.1f}h ({f.bearer_lifetime_seconds}s)""" if f.bearer_lifetime_seconds else f"""
- Bearer lifetime: unknown — check the JWT decode in findings.md
""" + f"""
- Refresh token in request body: `{f.refresh_request_carries_refresh_token}`
- Refresh response shape: see `findings.md` for the JSON paths.
"""
    p = out_dir / "how-to-wire-this-in.md"
    p.write_text(md)
    return p


def write_env(out_dir: Path, f: Findings) -> Path:
    envprefix = host_to_envvar(f.host)
    lines = []
    if f.bootstrap_bearer:
        lines.append(f"{envprefix}_AUTH_TOKEN='{f.bootstrap_bearer}'")
    if f.bootstrap_refresh:
        lines.append(f"{envprefix}_REFRESH_TOKEN='{f.bootstrap_refresh}'")
    p = out_dir / ".env"
    p.write_text("\n".join(lines) + "\n" if lines else "")
    try:
        p.chmod(0o600)
    except Exception:
        pass
    return p


# --- main ---


def main() -> None:
    ap = argparse.ArgumentParser(description="Borrow auth from a logged-in browser; find the refresh endpoint.")
    ap.add_argument("url", help="URL of the SPA (e.g. https://www.example.com)")
    ap.add_argument("--login-timeout-min", type=int, default=10, help="How long to wait for login (default 10)")
    args = ap.parse_args()

    out_dir = CONFIG_ROOT / urlparse(args.url).netloc
    try:
        findings = run(args.url, args.login_timeout_min)
    except SystemExit:
        raise
    except Exception as e:
        print(f"!!! Run errored mid-flow: {type(e).__name__}: {e}")
        print(f"    Writing whatever was captured to {out_dir}; see raw-capture.log for the rest.")
        findings = Findings(target_url=args.url, host=urlparse(args.url).netloc)

    findings_path = write_findings(out_dir, findings)
    guide_path = write_implementation_guide(out_dir, findings)
    env_path = write_env(out_dir, findings)

    print("\n=== SUMMARY ===")
    if findings.refresh_endpoint:
        print(f"refresh endpoint: {findings.refresh_method} {findings.refresh_endpoint}")
    else:
        print("refresh endpoint: NOT FOUND — see raw-capture.log to debug")
    if findings.bearer_lifetime_seconds:
        print(f"bearer lifetime:  {findings.bearer_lifetime_seconds}s ({findings.bearer_lifetime_seconds/3600:.1f}h)")
    print(f"bootstrap creds:  {env_path}")
    print(f"findings:         {findings_path}")
    print(f"impl guide:       {guide_path}")

    # Dump full findings as JSON sidecar for machine consumption.
    (out_dir / "findings.json").write_text(json.dumps(asdict(findings), indent=2, default=str))


if __name__ == "__main__":
    main()
