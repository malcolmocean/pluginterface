# og-image-drafting

A Claude Code skill for brainstorming and rendering illustration concepts for a blog post or article.

## What it does

When you ask Claude to "come up with illustration ideas for this post" (with a URL or text), the skill:

1. Reads the post.
2. Brainstorms 3 distinct single-scene illustration concepts and presents them to you in text — no API spend yet.
3. On your approval, generates each concept in 2+ art styles via the OpenAI Image API.
4. Builds an HTML gallery (3 columns, cards with image + post title in 20pt bold) and opens it in your browser.

## Why brainstorm first

Image generation costs ~$0.04–$0.19 per image. The first batch of concepts is often rejected — better to iterate in text than burn API spend on visuals you'll discard.

## Install

```bash
/plugin install og-image-drafting
```

## Requirements

- `OPENAI_API_KEY` in your environment (or in `~/.zshrc` — the script will fall back to it)
- Python 3 (standard library only, no extra deps)
- macOS `open` command for auto-opening the gallery (otherwise just open `index.html` manually)

## Output

A working directory like `system/illustration-exploration/2026-05-22-some-post-slug/` containing:

```
prompts.json     # the spec — edit and rerun to iterate
images/*.png     # generated illustrations
index.html       # gallery (auto-opens)
```

The script is idempotent: rerunning skips existing images, so rate-limit retries are cheap.

## Gallery format

3 columns (one per idea), responsive. Each card:

- Image in a bordered, drop-shadowed frame at 2:1 aspect ratio
- Post title below in 20pt bold

## Costs

A typical session of 6 images runs ~$0.25–$1.15. The full schema (3 ideas × 3 styles × 2 prompt variants = 18 images) runs ~$0.75–$3.45.
