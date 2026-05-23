"""Drive a round of OG-image / illustration drafting.

Reads a prompts.json describing ideas × styles, generates missing images via the
OpenAI Images API, and writes an index.html gallery alongside it.

Usage:
    python3 draft.py [prompts.json]

If prompts.json is omitted, defaults to ./prompts.json in the current directory.

prompts.json schema:

{
  "post_title": "NNTD pith instructions exploration",
  "size": "1536x1024",                # optional, defaults to 1536x1024
  "model": "gpt-image-1",             # optional
  "include_intent_variants": false,   # optional
  "ideas": {
    "1-cupped-hands": {
      "label": "Cupped hands holding water",
      "blurb": "Squeeze and you lose it.",
      "visual": "Two open hands ...",
      "intent": "Captures non-grasping presence."   # optional, used only if include_intent_variants
    }
  },
  "styles": {
    "minimalist": {
      "label": "Simple minimalist illustration",
      "prompt": "simple minimalist artistic illustration"
    }
  }
}

Idempotent: existing PNGs are skipped. HTML is always re-rendered.
"""

from __future__ import annotations

import base64
import concurrent.futures
import html
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request


DEFAULT_SIZE = "1536x1024"  # closest gpt-image-1 landscape size to 2:1
DEFAULT_MODEL = "gpt-image-1"
MAX_WORKERS = 4  # under the 5/min input-images rate limit for gpt-image-1


def load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    # Fallback: try to pull from ~/.zshrc
    zshrc = pathlib.Path.home() / ".zshrc"
    if zshrc.exists():
        for line in zshrc.read_text().splitlines():
            if line.startswith("export OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("OPENAI_API_KEY not set in env or ~/.zshrc")


def build_prompt(idea: dict, style: dict, with_intent: bool) -> str:
    parts = [idea["visual"]]
    if with_intent and idea.get("intent"):
        parts.append(idea["intent"])
    parts.append(f"Style: {style['prompt']}.")
    return " ".join(parts)


def generate_one(job: dict, api_key: str, model: str, size: str) -> dict:
    out_path = pathlib.Path(job["path"])
    if out_path.exists():
        print(f"skip  {out_path.name}", flush=True)
        return {**job, "status": "skipped"}

    payload = json.dumps({
        "model": model,
        "prompt": job["prompt"],
        "size": size,
        "n": 1,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    print(f"start {out_path.name}", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
        out_path.write_bytes(base64.b64decode(body["data"][0]["b64_json"]))
        print(f"done  {out_path.name}", flush=True)
        return {**job, "status": "ok"}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"FAIL  {out_path.name}: {e.code} {err}", flush=True)
        return {**job, "status": f"error {e.code}", "error": err}
    except Exception as e:
        print(f"FAIL  {out_path.name}: {e}", flush=True)
        return {**job, "status": "error", "error": str(e)}


def plan_jobs(spec: dict, img_dir: pathlib.Path) -> list[dict]:
    jobs = []
    variants = (["visual-only", "with-intent"]
                if spec.get("include_intent_variants") else ["visual-only"])
    for idea_key, idea in spec["ideas"].items():
        for style_key, style in spec["styles"].items():
            for variant in variants:
                with_intent = variant == "with-intent"
                # Skip with-intent if no intent text is provided
                if with_intent and not idea.get("intent"):
                    continue
                name_parts = [idea_key, style_key]
                if len(variants) > 1:
                    name_parts.append(variant)
                name = "__".join(name_parts)
                jobs.append({
                    "idea": idea_key,
                    "style": style_key,
                    "variant": variant,
                    "prompt": build_prompt(idea, style, with_intent),
                    "path": str(img_dir / f"{name}.png"),
                })
    return jobs


def render_html(spec: dict, jobs: list[dict], out_html: pathlib.Path,
                img_dir_rel: str) -> None:
    title = spec.get("post_title", "Illustration exploration")
    ideas = spec["ideas"]
    styles = spec["styles"]
    variants = (["visual-only", "with-intent"]
                if spec.get("include_intent_variants") else ["visual-only"])

    # Build column → cards mapping in order
    jobs_by_idea = {idea_key: [] for idea_key in ideas}
    for j in jobs:
        jobs_by_idea.setdefault(j["idea"], []).append(j)

    columns_html = []
    for idea_key, idea in ideas.items():
        cards = []
        for j in jobs_by_idea.get(idea_key, []):
            style_label = styles[j["style"]]["label"]
            tag = style_label
            if len(variants) > 1:
                tag = f"{style_label} · {j['variant']}"
            img_src = f"{img_dir_rel}/{pathlib.Path(j['path']).name}"
            cards.append(f"""
    <div class="card">
      <div class="variant-tag">{html.escape(tag)}</div>
      <div class="frame"><img src="{html.escape(img_src)}" alt=""></div>
      <div class="post-title">{html.escape(title)}</div>
    </div>""")
        columns_html.append(f"""
  <section class="column">
    <h2>{html.escape(idea.get('label', idea_key))}</h2>
    <p class="blurb">{html.escape(idea.get('blurb', ''))}</p>
    {''.join(cards)}
  </section>""")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} · illustration exploration</title>
<style>
  :root {{
    --bg: #f4f1ea;
    --card-bg: #ffffff;
    --ink: #1a1a1a;
    --muted: #6b6357;
    --rule: #d9d2c2;
    --shadow: 0 6px 18px rgba(0, 0, 0, 0.12), 0 2px 4px rgba(0, 0, 0, 0.06);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    line-height: 1.45;
  }}
  header {{ padding: 36px 40px 18px; border-bottom: 1px solid var(--rule); }}
  header h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: -0.01em; }}
  header p {{ margin: 0; color: var(--muted); font-size: 14px; max-width: 820px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat({len(ideas)}, minmax(0, 1fr));
    gap: 28px; padding: 28px 40px 60px;
  }}
  @media (max-width: 1100px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .column h2 {{ margin: 0 0 4px; font-size: 16px; letter-spacing: -0.005em; }}
  .column .blurb {{ margin: 0 0 18px; font-size: 13px; color: var(--muted); }}
  .card {{
    background: var(--card-bg); border: 1px solid var(--rule); border-radius: 10px;
    box-shadow: var(--shadow); padding: 14px 14px 18px; margin-bottom: 22px;
  }}
  .card .frame {{
    aspect-ratio: 2 / 1; overflow: hidden; border-radius: 6px;
    background: #ece7dc; margin-bottom: 14px;
  }}
  .card .frame img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .post-title {{
    font-size: 20pt; font-weight: 700; line-height: 1.15;
    letter-spacing: -0.01em; margin: 4px 2px 0;
  }}
  .variant-tag {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--muted); margin: 0 2px 6px;
  }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>Illustration exploration · {len(ideas)} concepts × {len(styles)} styles.</p>
</header>
<div class="grid">
{''.join(columns_html)}
</div>
</body>
</html>
"""
    out_html.write_text(page)


def main(argv: list[str]) -> int:
    prompts_path = pathlib.Path(argv[1]).resolve() if len(argv) > 1 else pathlib.Path("prompts.json").resolve()
    if not prompts_path.exists():
        raise SystemExit(f"prompts file not found: {prompts_path}")

    spec = json.loads(prompts_path.read_text())
    work_dir = prompts_path.parent
    img_dir = work_dir / "images"
    img_dir.mkdir(exist_ok=True)

    jobs = plan_jobs(spec, img_dir)
    if not jobs:
        raise SystemExit("No jobs planned — check prompts.json has ideas and styles.")

    api_key = load_key()
    model = spec.get("model", DEFAULT_MODEL)
    size = spec.get("size", DEFAULT_SIZE)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(generate_one, j, api_key, model, size) for j in jobs]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = [r for r in results if r["status"].startswith("error")]

    out_html = work_dir / "index.html"
    render_html(spec, jobs, out_html, "images")
    print(f"\nGenerated: {ok} new, {skipped} skipped, {len(failed)} failed.")
    print(f"HTML:  {out_html}")
    if failed:
        for f in failed:
            print(f"  - {pathlib.Path(f['path']).name}: {f['status']}")
        print("\nRerun this command to retry failed images (existing files are skipped).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
