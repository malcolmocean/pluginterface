---
name: clapboard
description: Use when the user wants to sync multiple audio/video files of the same event (e.g. interview with separate camera + audio recorder), pick a trim range, optionally crop, and produce a final muxed video without opening an NLE. Drives the `sync_trim.py` script (cross-correlation sync + mlx-whisper transcription of head/tail to help pick start/end).
---

# clapboard

Drives `/Users/malcolm/dev/pluginterface/plugins/clapboard/sync_trim.py` to
sync, trim, and optionally crop a folder of interview audio/video files. The
script handles offset detection (audio cross-correlation), transcription
(mlx-whisper), preview (ffplay), and final render (ffmpeg).

## When to use

- Multiple files captured simultaneously (camera + separate audio recorder,
  multiple cameras, etc.) that need to be synced.
- Goal is a single muxed video + per-file trimmed masters, without opening
  Resolve / Premiere / etc.
- User wants to trim head and tail (e.g. cut before the clapper, cut the
  goodbyes), and may want to crop one of the videos.

## Prerequisites — confirm before first run

- `ffmpeg`, `ffprobe`, `ffplay` on PATH (Homebrew).
- The clapboard project at `/Users/malcolm/dev/pluginterface/plugins/clapboard/`
  with `uv` deps installed (`uv sync` if needed).

## Workflow

Run from anywhere — pass the absolute folder path containing the media files.

### 1. Analyze

```bash
cd /Users/malcolm/dev/pluginterface/plugins/clapboard && uv run python sync_trim.py analyze "<folder>"
```

This prints to stderr:
- detected primary file (longest video by default)
- per-file offsets relative to primary
- a transcript of the first 60s and last 60s of primary, with timestamps

It also writes `<folder>/.audvid_state.json` for subsequent commands.

**Critical: the head/tail transcripts are PRIMARY's audio, not the audio
source's.** If you're going to mux audio.wav into primary's video, you have
not yet seen what audio.wav contains. Before picking a start, also
`transcribe` audio.wav at the corresponding range (audio_t = primary_t -
offset, where offset is the negative-valued number from the report). See the
"Pre-flight verification" section below.

### 2. Pre-flight verification — do this before asking start/end

Three checks that catch the failure modes in the "Gotchas" section. Cheap to
run; expensive to skip.

**a. Audio-source coverage.** Compute the primary-timeline window your audio
source actually covers:
```
covered = [ -offset, audio_duration - offset ]
```
e.g. audio.wav (4966s) with offset -294.7s covers primary [294.7, 4671.3].
Primary t=0..294.7 will play silence (audio.wav hadn't started recording yet);
primary t>4671.3 will play silence too. If your intended trim window falls
partly outside `covered`, you need a different audio source for that range —
or trim the window in.

**b. Multiple sessions in one take.** If the primary's head transcript shows
clapper / setup chatter for one cast, and audio.wav's first speech (after any
leading silence) is *different* setup chatter / a *different* cast, you have
two interviews back-to-back in the primary video — and audio.wav only covers
the second one. Look for two distinct "OK I got the board" / clapboard moments
in either file. Confirm with the user which session they want before
proceeding.

**c. Anchor the offset on a shared landmark.** Pick a phrase or sound event
that exists in *both* files (e.g. "Hi, hey" at the interview opener, or the
clapper count). Locate it in each file via `transcribe`, then verify
`primary_t = audio_t + offset` matches within ~1s. This catches a wrong
cross-correlation lock (rare but happens with mostly-silent tracks).

### 3. Pick start and end

Show the user the head + tail transcripts (you've already seen them on
stderr) AND the corresponding audio-source transcripts from pre-flight. Use
`AskUserQuestion` to ask for:
- `start` — timestamp in primary's timeline (seconds, or MM:SS, convert to
  seconds before passing)
- `end` — same. **Important: use the END timestamp of the last whisper
  segment you want to include, not the start.** Whisper segments span
  start→end; cutting at the start drops the segment's content.
- whether they want to crop the video; if yes, see "Crop selection via HTML
  preview" below
- whether `audio-source` should be primary or another file (default: primary)

Convert any `MM:SS` answers to seconds before invoking the script.

#### Visual options → HTML preview; timing → ffplay

Match the preview tool to the kind of decision:

- **Visual / spatial choices** (crops, framing, lower-thirds) — render
  side-by-side stills into an HTML file and `open` it. The user can revisit,
  zoom, A/B, and the comparison persists. See "Crop selection via HTML
  preview" below.
- **Timing choices** (start/end, mute/duck windows) — prefer the script's
  `preview` command (ffplay window that auto-closes after 15s). The forced
  real-time playback is a feature: it keeps the user engaged with the
  pacing and prevents drifting into pixel-peeping the wrong question. The
  brief on-screen interrupt is itself useful signal.
- **Hybrid: timing decisions the user wants to retry** (e.g. comparing two
  candidate end-cuts before committing to a 30+ min render) — render an
  ad-hoc clip with `ffmpeg` spanning the cut point with a `drawtext` second-
  counter overlay (`drawtext=text='t\\=%{eif\\:t+START\\:d}s':...`) and `open`
  it. The user can rescrub freely. Don't make this the default; use it when
  they ask for re-watchability or when the boundary timing matters more than
  the conversational feel.

#### Crop selection via HTML preview

Read-tool images often don't render inline in the user's UI (Claude Code
terminal in particular). When comparing multiple crop options, build a small
HTML file with `<img>` tags pointing to local jpgs and `open` it — the user
sees them in their browser.

Pattern:
1. Extract one reference frame from a representative mid-conversation
   moment (`ffmpeg -ss <t> -i <video> -frames:v 1 -q:v 2 /tmp/ref.jpg`).
2. For each candidate crop (call them B/C/D/E), render a still:
   `ffmpeg -ss <t> -i <video> -frames:v 1 -vf "crop=W:H:X:Y" -q:v 2 /tmp/crop_<id>.jpg`.
3. Write `/tmp/crop_compare.html` with a small dark-themed CSS, an `<img>`
   per option, and `<p class="meta">crop=W:H:X:Y</p>` under each so the user
   can quote-back the exact spec.
4. `open /tmp/crop_compare.html` to launch in default browser.

For a "does the crop hold across the whole conversation" check, also render
a 3×4 grid of ~12 evenly-spaced cropped frames (scaled to ~720w each) — same
pattern, plus a `position:absolute` timestamp badge per cell. This is how you
catch mid-clip framing issues (subject stands up, leans forward, etc.).

### 4. Preview

```bash
cd /Users/malcolm/dev/pluginterface/plugins/clapboard && uv run python sync_trim.py preview "<folder>" \
  --start <start> --end <end> [--audio-source <file>] [--crop <file>=<W:H:X:Y>] \
  [--polish-audio]
```

This renders a 15-second preview starting at `--start` and opens it in
`ffplay` (auto-exits when done). The preview muxes primary's video + the
chosen audio source, applies the crop, and (with `--polish-audio`) applies a
compressor → loudnorm (-16 LUFS) → limiter chain. **Recommend
`--polish-audio` by default for interview voice** — it raises the level to
YouTube/podcast loudness and tames laughter peaks. Skip only if the audio
is already mastered or if the user wants raw output.

After playback, ask the user via `AskUserQuestion`: "look good — render the
full thing? / adjust start/end / adjust crop / adjust polish / cancel".

If they want a different point previewed (e.g. near the end), call `preview`
again with a different `--start` (e.g. `--start (end - 15)`).

### 5. Render

```bash
cd /Users/malcolm/dev/pluginterface/plugins/clapboard && uv run python sync_trim.py render "<folder>" \
  --start <start> --end <end> \
  [--audio-source <file>] [--crop <file>=<W:H:X:Y>] \
  [--polish-audio] [--no-keep-trimmed] [--accurate-trim] [--outdir <dir>]
```

Default produces in `<folder>/output/`, with a `_<YYYYMMDD-HHMMSS>` suffix
on every output (no overwriting — each render is a fresh, comparable file):
- `<basename>_trimmed_<ts>.<ext>` for each video input (lossless `-c copy`)
- `<basename>_trimmed_[cut_][denoised_][polished_]<ts>.flac` for audio inputs
- `<primary-basename>_synced_<ts>.mp4` (final muxed video + chosen audio)

**Principle: never overwrite outputs.** This holds for one-off ffmpeg
invocations too (e.g. patching channels, re-rendering from existing
masters) — always write to a new path with a timestamp or descriptive
suffix. Avoids playback-of-partial-write confusion and lets you A/B
compare across attempts. The user's working drive has tons of space; old
attempts can be deleted manually when they're confirmed redundant.

Flags:
- `--polish-audio`: applies compressor + loudnorm + limiter to BOTH the
  muxed output AND the per-file trimmed audio masters (ZOOM/.WAV files etc).
  Trimmed video masters stay untouched (the audio-only files get polished;
  videos retain their original camera-mic audio for archival).
- `--no-keep-trimmed`: delete the per-file masters after muxing
- `--accurate-trim`: re-encode trimmed masters for frame accuracy (default
  uses `-c copy`, which may shift the cut by up to ~1s to the nearest
  keyframe — fine for interview head/tail). Note: audio-only masters are
  always re-encoded when `--polish-audio` is on.

After rendering, report the output paths to the user and offer to open the
muxed file in QuickTime (`open <path>`).

## Optional: targeted audio fixes (mute / duck / fade)

For isolated noise (cough, laugh, sneeze, door slam) inside an otherwise
keep-able stretch, the script supports three knobs on both `preview` and
`render`:

- `--mute "TS-TE"` — full silence on a primary-timeline range. Best when
  the noise sits in a clear gap from speech (≥200ms on both sides).
- `--duck "TS-TE@DB"` — partial attenuation (DB negative, e.g. `-25`).
  Best when the noise is close to speech and a full mute would clip word
  edges. **With `--polish-audio` on, you usually need −20 dB or deeper**
  (loudnorm/limiter rebalances the segment, so a −12 dB duck barely
  registers in the mastered output). Try −25 first; go deeper if needed.
- `--fade-out N` (with `--fade-out-curve log` for a steep early drop) —
  audio fade across the last N seconds of the trim. Useful for soft
  endings; if the user just wants the noise gone, prefer trimming the
  end shorter instead.

Workflow when the user reports a peak inside a stretch they want to keep:

1. `transcribe --start <s> --end <s> --words` over the suspect window —
   gives word boundaries so you know where speech sits.
2. Quick peak-scan in Python: extract the audio source's region with
   ffmpeg → `s16le` mono, compute 30ms-window RMS dB, mask the speech
   bands using the word timestamps, flag non-speech frames above
   `(speech_p90_dB − ~3)`. Group contiguous frames, expand by ~80–100ms
   pad, drop ranges overlapping speech. Print each candidate with peak
   dB so the user can sanity-check.
3. Calibration loop: render a short `preview` over the suspect window
   with `--mute` first (binary check that the window is hitting the
   noise), then switch to `--duck` and dial the dB until acceptable.

## Optional: ad-hoc transcription (no re-correlation)

If the user wants a transcript of a different range than the head/tail
analyze produced (e.g. "I need to find a cut point around 17 minutes in"),
use `transcribe` instead of re-running `analyze`:

```bash
cd /Users/malcolm/dev/pluginterface/plugins/clapboard && uv run python sync_trim.py transcribe \
  "<folder>" --start <s> --end <s> [--file <name>] [--words]
```

`--words` adds per-word timestamps (~50–200ms accuracy) — useful for
trimming right between specific words (e.g. cut just after the clapper).

## Optional: stitch multiple synced clips

After rendering each clip's `_synced.mp4`, concatenate them into one final:

```bash
cd /Users/malcolm/dev/pluginterface/plugins/clapboard && uv run python sync_trim.py stitch \
  -o <final.mp4> <clip-A_synced.mp4> <clip-B_synced.mp4> [...more]
```

Inputs in order. Tries `-c copy` (instant + lossless); falls back to
re-encode automatically if codecs/dimensions differ between inputs.

## Common adjustments / gotchas

- **Whisper model**: default is `whisper-small.en-mlx` (good enough for
  English interviews, ~5–15s for 2 minutes of audio on M1 Pro). If the user
  needs better transcription, pass `--model mlx-community/whisper-medium.en-mlx`
  to `analyze` or `transcribe`.
- **Tail length**: `--tail-seconds 300` on `analyze` covers a "last 5 min"
  transcript window; default is 60s.
- **Wrong primary**: if the longest-video heuristic picks the wrong file,
  pass `--primary <filename>` to `analyze`.
- **Sync looks off**: cross-correlation can lock onto the wrong feature if
  one track is mostly silence with one loud event vs another. Verify offsets
  in the printed report look plausible (interview clap is usually within a
  few seconds), and play the preview before rendering.
- **State stale**: the `.audvid_state.json` reflects the last `analyze` run.
  Re-run `analyze` if files in the folder change.
- **Crop syntax**: ffmpeg `crop=W:H:X:Y`. To get original dimensions:
  `ffprobe -v error -select_streams v -show_entries stream=width,height
  -of csv=p=0 <file>`.
- **Transcript timestamps aren't always file-absolute.** Whisper may anchor
  timestamps to its first detected speech rather than to file t=0, especially
  with long leading silence or VAD-style preprocessing. Don't blindly trust
  `[00:00] Foo` as "Foo is at file t=0" — cross-check by:
  - running `transcribe --start 0 --end <small>` and confirming the first
    non-silence timestamp matches an audio-level scan
    (`ffmpeg ... -af astats=metadata=1:reset=1,ametadata=print` shows RMS dB
    per window), or
  - verifying a known landmark phrase appears at the expected position in
    both files (see pre-flight check c).
  If a `[00:00]` timestamp turns out to be displaced, every subsequent
  timestamp in that transcript may be displaced by the same amount.
- **Killing a hung render.** Use specific PIDs, not pattern-matching:
  ```
  ps aux | grep sync_trim.py | grep -v grep   # find the python PID
  kill <pid>                                  # SIGTERM the parent; ffmpeg children exit
  ```
  Never `pkill -f ffmpeg` or `pkill -f python` — those will also kill
  unrelated work running on the machine. If background-task tooling tracked
  the PID at launch, prefer cancelling via that.
- **Confirm both edges of the trim before rendering.** A render of a 4K
  interview can be 30-60 min. Cheap sanity check: preview at `--start` AND at
  `--start (end - 15)` (or render a short ad-hoc clip spanning the proposed
  end with a timestamp overlay) before committing. The natural ending often
  sits a few seconds later than where the substantive talk wraps —
  audio-engineer chatter ("do we hit the clapper again?") frequently follows
  the actual conversational button.
