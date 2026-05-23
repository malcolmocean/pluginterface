# pluginterface

Malcolm's Claude Code plugins.

## Installation

```bash
/plugin marketplace add malcolmocean/pluginterface
```

Then browse and install plugins with `/plugin`.

## Plugins

### saywhen

Voice notifications using macOS text-to-speech. Announces when:
- Tasks complete
- Permission is needed
- Claude is idle
- User input is needed

```bash
/plugin install saywhen
```

### og-image-drafting

Brainstorm illustration concepts for a blog post, then generate side-by-side variants (concepts × art styles) via the OpenAI image API. Builds an HTML preview gallery so you can compare.

```bash
/plugin install og-image-drafting
```

### clapboard

Sync, trim, and master multi-track interview audio/video without an NLE.
Cross-correlation sync + mlx-whisper transcription of head/tail + ffmpeg
edits (cuts, mutes, ducks, fades, polish).

```bash
/plugin install clapboard
```

### throw-down-the-keys

Borrow auth state from a one-time browser login so an unattended CLI or
remote agent can stay logged in to a web app indefinitely. Drives Playwright
to find the SPA's silent-refresh endpoint, then writes bootstrap credentials
plus a language-agnostic implementation guide.

```bash
/plugin install throw-down-the-keys
```
