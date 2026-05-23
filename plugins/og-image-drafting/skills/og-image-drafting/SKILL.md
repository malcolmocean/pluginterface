---
name: og-image-drafting
description: Use when the user wants illustration / cover / OG image ideas for a blog post or article. Brainstorms 3 evocative single-scene concepts, then (on approval) generates them in multiple art styles via the OpenAI image API and assembles an HTML preview gallery.
---

# OG image drafting

Help the user explore illustration concepts for a piece of writing, then generate side-by-side variants and present them in a browser-viewable gallery.

## When to use

Trigger phrases include: "illustration ideas for this post", "cover image", "OG image", "header image", "illustrate this", "what should I put on…", or a shared URL with a request for a visual.

## The flow

Two phases, with a checkpoint between. **Do not skip the brainstorm checkpoint** — image generation costs ~$0.04–0.19 per image and the user usually iterates on concepts before committing to renders.

### Phase 1 — Read and brainstorm (no API spend)

1. If the user shared a URL, fetch the post with WebFetch. If they pasted text, work from that.
2. Generate **3 distinct illustration ideas**. Each should be:
   - A **single evocative scene/image**, not an infographic or diagram
   - Visually concrete (you should be able to picture it in one frame)
   - Distinct from the others in metaphor/mood, not three takes on the same image
3. Present each idea to the user as a short paragraph: a vivid visual description, followed by what it captures from the piece (one line). Say which is your favorite and why, and offer to riff in a different direction if none land.
4. **Stop and wait for the user's response.** They may approve, ask for new ideas, ask for variations, or pivot entirely.

### Phase 2 — Generate (only after user approval)

Once the user has signed off on the concepts (and ideally indicated styles or preferences):

1. **Pick a working directory.** A good default in a content repo is `system/illustration-exploration/<YYYY-MM-DD>-<slug>/`. If iterating after a rejected first round, append `-v2`, `-v3` so prior attempts stay on disk.
2. **Write `prompts.json` in that directory.** See "prompts.json schema" below. Default to 3 ideas × 2 styles = 6 images. Include `include_intent_variants: true` only if you want to A/B test prompts (doubles the count).
3. **Run the script:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/og-image-drafting/draft.py" path/to/prompts.json
   ```
   If `${CLAUDE_PLUGIN_ROOT}` isn't set, the script lives at `<this-skill-dir>/draft.py` — use the absolute path.
   The script:
   - Loads `OPENAI_API_KEY` from env, or from `~/.zshrc` as fallback
   - Generates with `gpt-image-1` at 1536×1024 (closest landscape to 2:1; displayed at exact 2:1 via CSS)
   - Runs 4 in parallel (under the 5/min rate limit)
   - **Skips images that already exist** — safe to rerun after rate-limit failures
   - Writes/refreshes `index.html` in the same directory
4. **Open the gallery:** `open <work-dir>/index.html`
5. If any failed (rate limit, etc.), just rerun the same command — existing files are skipped.

### Phase 3 — Iterate

If the user doesn't like the results:
- New concepts entirely → bump to a `-v2` directory, repeat Phase 1
- Same concepts, different style → edit `prompts.json` styles and rerun (existing images stay)
- Same concepts, refined prompts → delete the relevant PNGs and rerun

## prompts.json schema

```json
{
  "post_title": "NNTD pith instructions exploration",
  "size": "1536x1024",
  "include_intent_variants": false,
  "ideas": {
    "1-cupped-hands": {
      "label": "Cupped hands holding water",
      "blurb": "Squeeze and you lose it.",
      "visual": "Two open hands, palms up, fingers gently curved together to form a shallow bowl, cradling a small pool of clear still water. Hands relaxed, not gripping. Generous negative space. Wide horizontal framing.",
      "intent": "The image should evoke trust as something ungraspable."
    }
  },
  "styles": {
    "minimalist": {
      "label": "Simple minimalist illustration",
      "prompt": "simple minimalist artistic illustration"
    },
    "ink-lineart": {
      "label": "Minimalist ink line art",
      "prompt": "rendered as minimalist single-color ink line art on warm cream paper, confident sparse linework, generous negative space, no shading"
    }
  }
}
```

- `label` is what shows in column headings and card tags
- `blurb` is the one-liner under the column heading
- `visual` is the image prompt itself — keep it concrete and visual
- `intent` is optional; only used if `include_intent_variants: true`
- Idea/style keys are used in filenames (kebab-case, no spaces)

## Style suggestions (use the user's preferences first)

If the user hasn't expressed a preference, suggest 2–3 from this menu:

- **Simple minimalist artistic illustration** — clean, iconic, lots of negative space (a user favourite)
- **Minimalist ink line art on cream** — confident sparse linework, no fill
- **Two-tone risograph** — flat colors with print grain, editorial feel
- **Soft watercolor with ink linework** — gentle, contemplative, muted earthy palette
- **Cinematic photorealistic, golden hour** — painterly, emotional, shallow DoF
- **Mid-century modern / paper cut** — limited flat palette, geometric simplicity (Saul Bass / Eric Carle)

## Prompt-writing tips

- **Specify framing:** "wide horizontal framing" + "generous negative space" helps the 2:1 crop look intentional, not cropped
- **Be concrete:** "a small songbird perched on a person's upturned palm" beats "trust as a fragile thing"
- **Don't try to encode the full thesis in one image.** Pick one facet of the piece.
- **Single-scene over multi-panel:** image models don't reliably do composites — one image, one moment.
- **Watch for cliché:** trust/love/connection imagery is full of clichés (hands reaching, doves, hearts). Pick a fresher angle.
- **For minimalist styles:** keep prompts shorter; too much detail confuses the model and clutters the image.

## Costs and limits

- gpt-image-1: roughly $0.04 (low quality) to $0.19 (high quality) per 1536×1024 image
- Rate limit: 5 images per minute. The script paces with 4 workers; rate-limit failures are common on the first batch of 9+ — just rerun.
- 12 images at default quality ≈ $0.50–$2.30 total

## Gallery layout

The generated `index.html` is a 3-column responsive grid (one column per idea). Each card has the image in a bordered, drop-shadowed frame followed by the post title in 20pt bold. The display frame is forced to 2:1 via CSS (`aspect-ratio: 2 / 1` + `object-fit: cover`).

## Iteration patterns observed

- The first batch is often rejected wholesale — the user is locating their taste, not your taste.
- Asking "do any of these land?" is more useful than "which is your favorite?"
- When the user says "I tried X style and liked it more" — they're handing you a free win; quote their phrasing back verbatim in the next round's style prompt.
- Preserve prior rounds in numbered folders. The rejected ones are reference for what *not* to do.
