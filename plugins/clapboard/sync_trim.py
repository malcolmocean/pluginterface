#!/usr/bin/env python3
"""sync_trim — sync, transcribe, trim audio/video for interviews.

Subcommands:
  analyze  Detect offsets across files (audio cross-correlation); transcribe
           head and tail of the primary file. Writes .audvid_state.json.
  preview  Render a 15s preview at chosen start; play via ffplay.
  render   Produce per-file trimmed masters + a muxed video+audio output.

Time references: --start/--end are in the *primary* file's timeline. Other
files are aligned by the detected offsets.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def render_stamp() -> str:
    """Compact, sortable timestamp suffix for output filenames. Each render
    invocation produces fresh files (no overwriting) so prior renders stay
    available for A/B comparison and to avoid playback-of-partial-write
    confusion while a re-render is in flight."""
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

import numpy as np
from scipy.signal import correlate

MEDIA_EXTS = {".mp4", ".mov", ".m4a", ".wav", ".mp3", ".aac", ".flac",
              ".mkv", ".avi", ".webm", ".m4v"}
STATE_FILENAME = ".audvid_state.json"
CORR_SR = 4000  # downsample audio to this for cross-correlation
DEFAULT_MODEL = "mlx-community/whisper-small.en-mlx"

# When forced to re-encode video (cuts/crop), use Apple's hardware HEVC
# encoder. ~5-10x realtime on M1 vs libx264/265 software, preserves 10-bit
# (p010le), and at -q:v 65 is visually transparent vs typical phone HDR
# source. -tag:v hvc1 is for QuickTime / Apple Photos compatibility.
VIDEO_ENCODE_ARGS = [
    "-c:v", "hevc_videotoolbox",
    "-q:v", "65",
    "-tag:v", "hvc1",
    "-pix_fmt", "p010le",
    "-profile:v", "main10",
    "-c:a", "aac",
    "-b:a", "256k",
]
# Trimmed audio masters: FLAC (lossless, no 4GB filesize limit like WAV,
# ~50% the size of equivalent PCM). The right archival format. Convert to
# MP3 / etc downstream when handing off to a transcriber or similar.
AUDIO_MASTER_ENCODE_ARGS = ["-c:a", "flac", "-compression_level", "5"]
AUDIO_MASTER_EXT = ".flac"

# Light compressor → EBU R128 loudnorm (-16 LUFS, YouTube voice target)
# → brick-wall limiter at ~-1.5 dBTP (linear 0.841) for laughter/peaks.
POLISH_AUDIO_CHAIN = (
    "acompressor=threshold=-20dB:ratio=2.5:attack=20:release=250,"
    "loudnorm=I=-16:TP=-1.5:LRA=11,"
    "alimiter=limit=0.841"
)

# afftdn: FFT-based denoiser. nr=12 dB reduction is moderate (preserves voice
# texture); nt=w trains noise profile from the loudest non-speech moments.
DENOISE_CHAIN = "afftdn=nr=12:nt=w"


def _cuts_expr(cuts: list[tuple[float, float]]) -> str:
    """Build an aselect/select expression that's true OUTSIDE the cut ranges."""
    inside = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cuts)
    return f"not({inside})"


def build_video_filter(*, cuts: list[tuple[float, float]] | None = None,
                       crop: str | None = None) -> str:
    parts = []
    if cuts:
        parts.append(f"select='{_cuts_expr(cuts)}'")
        # For each kept frame, advance the output PTS by the input
        # inter-frame interval (preserves source VFR — e.g. Pixel HEVC at
        # "30fps" averages ~29.78). When the input gap is large (>2x the
        # nominal frame period), it's the cut boundary — collapse it to a
        # single nominal interval so the cut is seamless.
        parts.append(
            "setpts='if(isnan(PREV_OUTPTS),0,"
            "if(gt(PTS-PREV_INPTS,2/FRAME_RATE/TB),"
            "PREV_OUTPTS+1/FRAME_RATE/TB,"
            "PREV_OUTPTS+PTS-PREV_INPTS))'"
        )
    if crop:
        parts.append(f"crop={crop}")
    return ",".join(parts)


def build_audio_filter(*, pad_dur: float | None = None,
                       pad_target_dur: float | None = None,
                       cuts: list[tuple[float, float]] | None = None,
                       mutes: list[tuple[float, float]] | None = None,
                       ducks: list[tuple[float, float, float]] | None = None,
                       swap_channels: bool = False,
                       denoise: bool = False,
                       polish: bool = False,
                       fade_in: float | None = None,
                       fade_out: float | None = None,
                       fade_out_curve: str = "tri",
                       window_dur: float | None = None) -> str:
    """Compose audio filter chain. Order: pad → cut → mute → duck → swap → denoise → polish → fade.

    Cut/mute/duck are BEFORE denoise+polish so loudnorm sees the final
    post-edit signal and normalizes consistently. `cuts` and `mutes` are
    window-relative (start, end) pairs; `ducks` are (start, end, db) where
    db is negative (e.g. -12 for a 12 dB attenuation). `fade_in` /
    `fade_out` are durations in seconds applied at the very end of the
    chain (after polish, so the fade is on the final mastered signal).
    `fade_out` requires `window_dur` so the start time can be computed.
    """
    parts = []
    if pad_dur is not None and pad_dur > 0:
        pad_ms = int(round(pad_dur * 1000))
        parts.append(
            f"adelay={pad_ms}|{pad_ms},apad=pad_dur={pad_dur}"
            + (f",atrim=duration={pad_target_dur}"
               if pad_target_dur is not None else "")
        )
    if cuts:
        parts.append(f"aselect='{_cuts_expr(cuts)}'")
        parts.append("asetpts=N/SR/TB")
    if mutes:
        for s, e in mutes:
            parts.append(f"volume=0:enable=between(t\\,{s:.3f}\\,{e:.3f})")
    if ducks:
        for s, e, db in ducks:
            parts.append(
                f"volume={db:.2f}dB:enable=between(t\\,{s:.3f}\\,{e:.3f})"
            )
    if swap_channels:
        parts.append("pan=stereo|c0=c1|c1=c0")
    if denoise:
        parts.append(DENOISE_CHAIN)
    if polish:
        parts.append(POLISH_AUDIO_CHAIN)
    if fade_in and fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out and fade_out > 0:
        if window_dur is None:
            raise ValueError("fade_out requires window_dur")
        st = max(0.0, window_dur - fade_out)
        parts.append(
            f"afade=t=out:st={st:.3f}:d={fade_out:.3f}:curve={fade_out_curve}"
        )
    return ",".join(parts)


def parse_mutes(raw: list[str] | None, *, trim_start: float
                ) -> list[tuple[float, float]]:
    """--mute "TS-TE" (each in primary timeline, seconds or M:SS) → list of
    (output_start, output_end) for the volume=0 filter.
    """
    if not raw:
        return []
    out = []
    for r in raw:
        if "-" not in r:
            sys.exit(f"Bad --mute {r!r}: expected TS-TE")
        a, b = r.split("-", 1)
        ts, te = parse_time(a), parse_time(b)
        if te <= ts:
            sys.exit(f"Bad --mute {r!r}: end must be > start")
        out.append((ts - trim_start, te - trim_start))
    return out


def parse_ducks(raw: list[str] | None, *, trim_start: float
                ) -> list[tuple[float, float, float]]:
    """--duck "TS-TE@DB" (TS,TE in primary timeline; DB negative, e.g. -12)
    → list of (output_start, output_end, db) for the volume filter. The DB
    suffix is required (no default — explicit is safer for an audio edit).
    """
    if not raw:
        return []
    out = []
    for r in raw:
        if "@" not in r or "-" not in r:
            sys.exit(f"Bad --duck {r!r}: expected TS-TE@DB (e.g. 60-61@-12)")
        rng, db_s = r.rsplit("@", 1)
        a, b = rng.split("-", 1)
        ts, te = parse_time(a), parse_time(b)
        try:
            db = float(db_s)
        except ValueError:
            sys.exit(f"Bad --duck {r!r}: DB must be a number")
        if te <= ts:
            sys.exit(f"Bad --duck {r!r}: end must be > start")
        if db >= 0:
            sys.exit(f"Bad --duck {r!r}: DB must be negative (attenuation)")
        out.append((ts - trim_start, te - trim_start, db))
    return out


def parse_time(s: str) -> float:
    """Accept '72:41.5', '4361.5', '1:12:41.5'."""
    s = s.strip()
    if ":" not in s:
        return float(s)
    parts = s.split(":")
    parts = [float(p) for p in parts]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    sys.exit(f"Bad time {s!r}")


# ---------- helpers ----------

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def has_video_stream(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return bool(out)


def extract_audio_array(path: Path, sr: int = CORR_SR) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def find_offset(primary: np.ndarray, other: np.ndarray, sr: int = CORR_SR) -> float:
    """Return offset in seconds: how much later `other` started than `primary`.

    primary[t] ≈ other[t - offset]. Positive offset means `other` started
    later in real time, so the same wall-clock event appears earlier in
    `other`'s local timeline.
    """
    a = primary - primary.mean()
    b = other - other.mean()
    a /= np.linalg.norm(a) + 1e-12
    b /= np.linalg.norm(b) + 1e-12
    corr = correlate(a, b, mode="full", method="fft")
    lag = int(np.argmax(corr)) - (len(b) - 1)
    return lag / sr


def find_robust_offset(primary: np.ndarray, other: np.ndarray,
                       initial_offset: float, sr: int = CORR_SR,
                       *, n_windows: int = 8, win_dur: float = 30.0,
                       search_dur: float = 1.0,
                       min_corr: float = 0.12) -> dict:
    """Refine `initial_offset` by cross-correlating at N windows across the
    primary, then taking the median.

    A single full-file correlation tends to lock onto whichever moment in
    the recording has the most distinctive signal, which can be biased a
    few tens of ms off the typical alignment. Windowed correlation reveals
    both that bias (median ≠ initial) and clock drift across the file
    (linear slope across windows).

    Returns:
      base: median of windowed offsets (the value to actually use in
            render — robust to outlier windows)
      drift_rate_ppm: linear slope of offset(t), positive = `other` clock
                      runs slower than primary, accumulating delay
      residual_std_ms: std dev of windows from the median (sanity signal)
      max_dev_ms: largest abs deviation from median across windows
      windows: list of per-window {t, offset, corr_peak} for diagnostics
      fallback: True if file too short for windowed analysis; base = initial
    """
    primary_dur = len(primary) / sr

    margin = max(15.0, win_dur)
    if primary_dur < 2 * margin + win_dur:
        return {"base": initial_offset, "drift_rate_ppm": 0.0,
                "residual_std_ms": 0.0, "max_dev_ms": 0.0,
                "windows": [], "fallback": True}

    times = np.linspace(margin, primary_dur - margin - win_dur,
                        n_windows).tolist()

    win_n = int(win_dur * sr)
    search_n = int(search_dur * sr)

    results: list[tuple[float, float, float]] = []
    for t in times:
        i0 = int(t * sr)
        prim_chunk = primary[i0:i0 + win_n]
        # `other`'s local time corresponding to primary's real time t is
        # (t - initial_offset). Extract a window centered there with
        # ±search_dur padding so cross-correlation has slack to find the
        # true peak even if local offset != initial_offset.
        j_center = (t - initial_offset) * sr
        j0 = int(j_center - search_n)
        j1 = int(j_center + win_n + search_n)
        if j0 < 0 or j1 > len(other):
            continue
        other_chunk = other[j0:j1]
        a = prim_chunk - prim_chunk.mean()
        b = other_chunk - other_chunk.mean()
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na < 1e-9 or nb < 1e-9:
            continue
        a /= na
        b /= nb
        corr = correlate(a, b, mode="full", method="fft")
        lag = int(np.argmax(corr)) - (len(b) - 1)
        # Perfect alignment (true_offset == initial_offset) means b's
        # content is shifted `search_n` samples left of a, so lag = -search_n.
        # General case: true_offset = initial_offset + (lag + search_n) / sr.
        true_offset = initial_offset + (lag + search_n) / sr
        peak = float(corr.max())
        results.append((t, true_offset, peak))

    if not results:
        return {"base": initial_offset, "drift_rate_ppm": 0.0,
                "residual_std_ms": 0.0, "max_dev_ms": 0.0,
                "windows": [], "fallback": True}

    confident = [r for r in results if r[2] >= min_corr]
    if len(confident) < 3:
        confident = results

    ts_ = np.array([r[0] for r in confident])
    offs = np.array([r[1] for r in confident])
    base = float(np.median(offs))

    if len(confident) >= 3:
        slope, _ = np.polyfit(ts_, offs, 1)
        drift_ppm = float(slope * 1e6)
    else:
        drift_ppm = 0.0

    residual_std_ms = float(np.std(offs - base) * 1000)
    max_dev_ms = float(np.max(np.abs(offs - base)) * 1000)

    return {"base": base, "drift_rate_ppm": drift_ppm,
            "residual_std_ms": residual_std_ms,
            "max_dev_ms": max_dev_ms,
            "windows": [{"t": float(r[0]), "offset": float(r[1]),
                         "corr_peak": float(r[2])} for r in results],
            "fallback": False}


def transcribe_segment(path: Path, start: float, duration: float,
                       model: str = DEFAULT_MODEL,
                       words: bool = False) -> list[dict]:
    import mlx_whisper
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav = Path(tf.name)
    try:
        run(["ffmpeg", "-v", "error", "-y",
             "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
             "-i", str(path), "-ac", "1", "-ar", "16000", str(wav)])
        result = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model,
                                        word_timestamps=words)
        out = []
        for s in result["segments"]:
            seg = {"start": s["start"] + start,
                   "end": s["end"] + start,
                   "text": s["text"].strip()}
            if words and "words" in s:
                seg["words"] = [
                    {"word": w["word"],
                     "start": w["start"] + start,
                     "end": w["end"] + start}
                    for w in s["words"]
                ]
            out.append(seg)
        return out
    finally:
        wav.unlink(missing_ok=True)


def fmt_t(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def parse_crops(crop_args: list[str]) -> dict[str, str]:
    """--crop FILE=W:H:X:Y → {FILE: "W:H:X:Y"}"""
    out = {}
    for c in crop_args:
        if "=" not in c:
            sys.exit(f"Bad --crop: {c!r} (expected FILE=W:H:X:Y)")
        name, spec = c.split("=", 1)
        out[name] = spec
    return out


def state_path_for(folder: Path) -> Path:
    return folder / STATE_FILENAME


def play_in(player: str, path: Path) -> None:
    if player == "none":
        return
    if player == "vlc":
        subprocess.run(["open", "-a", "VLC", str(path)])
    elif player == "ffplay":
        subprocess.run(["ffplay", "-autoexit", "-loglevel", "error", str(path)])
    else:
        sys.exit(f"Unknown --player: {player!r}")


def load_state(folder: Path) -> dict:
    p = state_path_for(folder)
    if not p.exists():
        sys.exit(f"No state file at {p}. Run `analyze` first.")
    return json.loads(p.read_text())


# ---------- subcommands ----------

def cmd_analyze(args):
    folder = Path(args.folder).resolve()
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in MEDIA_EXTS)
    if not files:
        sys.exit(f"No media files in {folder}")

    durs = {p.name: ffprobe_duration(p) for p in files}

    if args.primary:
        primary_name = args.primary
        if primary_name not in durs:
            sys.exit(f"--primary {primary_name!r} not in folder")
    else:
        # default primary: longest file with video, else longest file
        with_video = [p for p in files if has_video_stream(p)]
        candidates = with_video if with_video else files
        primary_name = max(candidates, key=lambda p: durs[p.name]).name

    primary = folder / primary_name
    print(f"Primary: {primary_name} ({durs[primary_name]:.1f}s)", file=sys.stderr)

    print("Extracting primary audio for sync...", file=sys.stderr)
    primary_audio = extract_audio_array(primary, CORR_SR)

    offsets = {primary_name: 0.0}
    offset_curves: dict[str, dict] = {}
    for p in files:
        if p.name == primary_name:
            continue
        print(f"  correlating {p.name}...", file=sys.stderr)
        other_audio = extract_audio_array(p, CORR_SR)
        global_off = find_offset(primary_audio, other_audio, CORR_SR)
        print(f"    global offset: {global_off:+.4f}s (rough)", file=sys.stderr)
        print(f"    refining via windowed correlation...", file=sys.stderr)
        curve = find_robust_offset(primary_audio, other_audio, global_off,
                                   CORR_SR)
        curve["global_offset"] = global_off
        offsets[p.name] = curve["base"]
        offset_curves[p.name] = curve
        if curve["fallback"]:
            print(f"    too short for windowed analysis — using global "
                  f"{global_off:+.4f}s", file=sys.stderr)
            continue
        base = curve["base"]
        delta_ms = (base - global_off) * 1000
        print(f"    robust base: {base:+.4f}s  "
              f"(global was off by {delta_ms:+.1f}ms)", file=sys.stderr)
        print(f"    drift: {curve['drift_rate_ppm']:+.1f}ppm  "
              f"(~{curve['drift_rate_ppm'] * durs[p.name] / 1000:+.1f}ms "
              f"across file)", file=sys.stderr)
        print(f"    sanity: max window deviation "
              f"{curve['max_dev_ms']:.1f}ms, std {curve['residual_std_ms']:.1f}ms",
              file=sys.stderr)
        warn = []
        if curve["max_dev_ms"] > 50:
            warn.append(f"max window deviation {curve['max_dev_ms']:.1f}ms "
                        f">50ms (audio may have splices, dropouts, or two "
                        f"recordings stitched together)")
        if abs(curve["drift_rate_ppm"]) > 50:
            warn.append(f"clock drift {curve['drift_rate_ppm']:+.1f}ppm "
                        f">50ppm (consider time-stretch correction; the "
                        f"recorder's clock differs meaningfully from camera)")
        if curve["residual_std_ms"] > 30:
            warn.append(f"window-offset std {curve['residual_std_ms']:.1f}ms "
                        f">30ms (correlation may be unreliable — verify "
                        f"sync by ear before final render)")
        for w in warn:
            print(f"    !! WARNING: {w}", file=sys.stderr)

    # transcribe head & tail of primary
    head_dur = min(args.head_seconds, durs[primary_name])
    tail_start = max(head_dur, durs[primary_name] - args.tail_seconds)
    tail_dur = durs[primary_name] - tail_start

    print(f"Transcribing head 0..{head_dur:.0f}s...", file=sys.stderr)
    head = transcribe_segment(primary, 0.0, head_dur, model=args.model,
                              words=args.words)
    tail = []
    if tail_dur > 0.5:
        print(f"Transcribing tail {tail_start:.0f}..{durs[primary_name]:.0f}s...",
              file=sys.stderr)
        tail = transcribe_segment(primary, tail_start, tail_dur,
                                  model=args.model, words=args.words)

    state = {
        "folder": str(folder),
        "primary": primary_name,
        "files": [p.name for p in files],
        "durations": durs,
        "offsets": offsets,
        "offset_curves": offset_curves,
        "head_transcript": head,
        "tail_transcript": tail,
    }
    state_path_for(folder).write_text(json.dumps(state, indent=2))

    print("\n=== OFFSETS (relative to primary) ===", file=sys.stderr)
    for n, o in offsets.items():
        marker = "  *" if n == primary_name else "   "
        print(f"{marker} {n}: {o:+.3f}s  (dur {durs[n]:.1f}s)", file=sys.stderr)

    def _print_segments(label, segs):
        print(f"\n=== {label} ===", file=sys.stderr)
        for s in segs:
            print(f"  [{fmt_t(s['start'])}] {s['text']}", file=sys.stderr)
            if args.words and s.get("words"):
                for w in s["words"]:
                    print(f"     [{fmt_t(w['start'])}] {w['word']}",
                          file=sys.stderr)

    _print_segments("HEAD TRANSCRIPT", head)
    if tail:
        _print_segments("TAIL TRANSCRIPT", tail)

    print(json.dumps(state))


def _build_trim_cmd(src: Path, src_start: float, dur: float, *,
                    out: Path, video_filter: str | None,
                    is_video: bool, fast_copy: bool,
                    audio_filter: str | None = None) -> list[str]:
    """Build ffmpeg cmd to trim `src` to [src_start, src_start+dur].

    If src_start < 0, pads the front with silence/black so the output starts
    at the requested common-timeline position. `video_filter` /
    `audio_filter` are appended (already built by build_video_filter /
    build_audio_filter).
    """
    cmd = ["ffmpeg", "-y", "-v", "error"]

    if src_start >= 0:
        if fast_copy and not video_filter and not audio_filter:
            cmd += ["-ss", f"{src_start:.3f}", "-i", str(src),
                    "-t", f"{dur:.3f}", "-c", "copy", str(out)]
            return cmd
        cmd += ["-ss", f"{src_start:.3f}", "-i", str(src), "-t", f"{dur:.3f}"]
        if video_filter and is_video:
            cmd += ["-vf", video_filter]
        if audio_filter:
            cmd += ["-af", audio_filter]
        cmd += [str(out)]
        return cmd

    # src_start < 0: pad front
    pad = -src_start
    real_dur = dur - pad
    if real_dur <= 0:
        real_dur = 0
    cmd += ["-i", str(src), "-t", f"{real_dur:.3f}"]
    pad_ms = int(round(pad * 1000))
    af_parts = [f"adelay={pad_ms}|{pad_ms},apad=pad_dur={pad}"]
    if audio_filter:
        af_parts.append(audio_filter)
    vf_parts = []
    if is_video:
        vf_parts.append(f"tpad=start_duration={pad}:start_mode=add:color=black")
        if video_filter:
            vf_parts.append(video_filter)
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    cmd += ["-af", ",".join(af_parts), "-t", f"{dur:.3f}", str(out)]
    return cmd


def cmd_preview(args):
    folder = Path(args.folder).resolve()
    state = load_state(folder)
    primary_name = state["primary"]
    primary = folder / primary_name
    audio_source = args.audio_source or primary_name
    audio_path = folder / audio_source
    if audio_source not in state["offsets"]:
        sys.exit(f"--audio-source {audio_source!r} not in state")

    crops = parse_crops(args.crop or [])
    start = args.start
    if args.end is not None:
        dur = min(args.duration, max(0.1, args.end - start))
    else:
        dur = args.duration

    p_start = start  # primary timeline ref
    a_start = start - state["offsets"][audio_source]

    out = (Path(tempfile.gettempdir())
           / f"audvid_preview_{render_stamp()}.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    # video from primary
    if p_start < 0:
        sys.exit(f"start ({start}) is before primary begins")
    cmd += ["-ss", f"{p_start:.3f}", "-t", f"{dur:.3f}", "-i", str(primary)]
    # audio from chosen source
    if a_start < 0:
        # pad with silence using anullsrc concatenated… simpler: use adelay on the file
        cmd += ["-i", str(audio_path)]
    else:
        cmd += ["-ss", f"{a_start:.3f}", "-t", f"{dur:.3f}", "-i", str(audio_path)]

    cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    crop = crops.get(primary_name)
    cuts = parse_mutes(args.cut, trim_start=start) if args.cut else []

    af = build_audio_filter(
        pad_dur=(-a_start if a_start < 0 else None),
        pad_target_dur=(dur if a_start < 0 else None),
        cuts=cuts or None,
        mutes=parse_mutes(args.mute, trim_start=start),
        ducks=parse_ducks(args.duck, trim_start=start),
        swap_channels=args.swap_channels,
        denoise=args.denoise,
        polish=args.polish_audio,
        fade_in=args.fade_in,
        fade_out=args.fade_out,
        fade_out_curve=args.fade_out_curve,
        window_dur=dur,
    )
    vf = build_video_filter(cuts=cuts or None, crop=crop)
    if af:
        cmd += ["-af", af]
    if vf:
        cmd += ["-vf", vf]

    cmd += VIDEO_ENCODE_ARGS + [str(out)]
    run(cmd)

    print(f"Preview: {out}", file=sys.stderr)
    play_in("none" if args.no_play else args.player, out)
    print(str(out))


def cmd_render(args):
    folder = Path(args.folder).resolve()
    state = load_state(folder)
    primary_name = state["primary"]
    start, end = args.start, args.end
    if end <= start:
        sys.exit("--end must be greater than --start")
    dur = end - start
    crops = parse_crops(args.crop or [])

    outdir = Path(args.outdir).resolve() if args.outdir else (folder / "output")
    outdir.mkdir(exist_ok=True)

    ts = render_stamp()
    cuts = parse_mutes(args.cut, trim_start=start) if args.cut else []
    mutes = parse_mutes(args.mute, trim_start=start) if args.mute else []
    ducks = parse_ducks(args.duck, trim_start=start) if args.duck else []

    # 1. trimmed masters
    #    - Video files: always -c copy raw trim (lossless, archival). Cuts
    #      and crop are NOT applied to video masters — those edits live in
    #      the muxed output. Masters preserve maximum source quality and
    #      flexibility for re-editing later.
    #    - Audio files: re-encode (lossless WAV/PCM container) with denoise
    #      / polish / cuts / mutes applied. The polished audio IS the
    #      deliverable for that source.
    trimmed_paths = []
    for fname in state["files"]:
        path = folder / fname
        offset = state["offsets"][fname]
        f_start = start - offset
        f_end = end - offset
        if f_end <= 0 or f_start >= state["durations"][fname]:
            print(f"  skipping {fname}: outside of file range", file=sys.stderr)
            continue
        is_video = has_video_stream(path)
        out_stem = Path(fname).stem
        out_ext = Path(fname).suffix

        if is_video:
            # raw trim, no edits — lossless -c copy
            out_path = outdir / f"{out_stem}_trimmed_{ts}{out_ext}"
            cmd = ["ffmpeg", "-y", "-v", "error",
                   "-ss", f"{max(0.0, f_start):.3f}",
                   "-i", str(path),
                   "-t", f"{dur:.3f}",
                   "-c", "copy", str(out_path)]
            print(f"  trimming {fname} → {out_path.name} (-c copy)",
                  file=sys.stderr)
        else:
            # audio: apply edits, write PCM 24-bit
            suffix_bits = []
            if cuts:
                suffix_bits.append("cut")
            if args.denoise:
                suffix_bits.append("denoised")
            if args.polish_audio:
                suffix_bits.append("polished")
            suffix = ("_trimmed_" + "_".join(suffix_bits)
                      if suffix_bits else "_trimmed")
            out_path = outdir / f"{out_stem}{suffix}_{ts}{AUDIO_MASTER_EXT}"
            af = build_audio_filter(
                cuts=cuts or None,
                mutes=mutes or None,
                ducks=ducks or None,
                swap_channels=args.swap_channels,
                denoise=args.denoise,
                polish=args.polish_audio,
                fade_in=args.fade_in,
                fade_out=args.fade_out,
                fade_out_curve=args.fade_out_curve,
                window_dur=dur,
            )
            cmd = ["ffmpeg", "-y", "-v", "error",
                   "-ss", f"{max(0.0, f_start):.3f}",
                   "-i", str(path),
                   "-t", f"{dur:.3f}"]
            if af:
                cmd += ["-af", af]
            cmd += AUDIO_MASTER_ENCODE_ARGS + [str(out_path)]
            print(f"  trimming {fname} → {out_path.name}", file=sys.stderr)
        run(cmd)
        trimmed_paths.append(out_path)

    # 2. muxed final
    audio_source = args.audio_source or primary_name
    if audio_source not in state["offsets"]:
        sys.exit(f"--audio-source {audio_source!r} not in state")
    primary = folder / primary_name
    audio_path = folder / audio_source
    a_start = start - state["offsets"][audio_source]
    p_start = start

    final = outdir / f"{Path(primary_name).stem}_synced_{ts}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", f"{max(0.0, p_start):.3f}", "-t", f"{dur:.3f}", "-i", str(primary)]
    if a_start < 0:
        cmd += ["-i", str(audio_path)]
    else:
        cmd += ["-ss", f"{a_start:.3f}", "-t", f"{dur:.3f}", "-i", str(audio_path)]
    cmd += ["-map", "0:v:0", "-map", "1:a:0"]

    crop = crops.get(primary_name)
    af = build_audio_filter(
        pad_dur=(-a_start if a_start < 0 else None),
        pad_target_dur=(dur if a_start < 0 else None),
        cuts=cuts or None,
        mutes=mutes or None,
        ducks=ducks or None,
        swap_channels=args.swap_channels,
        denoise=args.denoise,
        polish=args.polish_audio,
        fade_in=args.fade_in,
        fade_out=args.fade_out,
        fade_out_curve=args.fade_out_curve,
        window_dur=dur,
    )
    vf = build_video_filter(cuts=cuts or None, crop=crop)
    if af:
        cmd += ["-af", af]
    if vf:
        cmd += ["-vf", vf]
    cmd += VIDEO_ENCODE_ARGS + [str(final)]
    print(f"  muxing → {final.name}", file=sys.stderr)
    run(cmd)

    if not args.keep_trimmed:
        for p in trimmed_paths:
            p.unlink(missing_ok=True)
        print(f"  removed {len(trimmed_paths)} trimmed master(s)", file=sys.stderr)

    print(str(final))


def cmd_transcribe(args):
    """Ad-hoc transcription of a time range, without re-running correlation."""
    folder = Path(args.folder).resolve()
    state = load_state(folder)
    fname = args.file or state["primary"]
    if fname not in state["durations"]:
        sys.exit(f"--file {fname!r} not in state")
    target = folder / fname
    end = args.end if args.end is not None else state["durations"][fname]
    start = args.start
    if end <= start:
        sys.exit("--end must be greater than --start")
    dur = end - start
    print(f"Transcribing {fname} from {fmt_t(start)} to {fmt_t(end)} "
          f"({dur:.0f}s)...", file=sys.stderr)
    segs = transcribe_segment(target, start, dur, model=args.model,
                              words=args.words)
    print(file=sys.stderr)
    for s in segs:
        print(f"  [{fmt_t(s['start'])}] {s['text']}", file=sys.stderr)
        if args.words and s.get("words"):
            for w in s["words"]:
                print(f"     [{fmt_t(w['start'])}] {w['word']}", file=sys.stderr)
    print(json.dumps(segs))


def cmd_stitch(args):
    """Concatenate multiple rendered files into one. Tries -c copy, falls
    back to re-encode if codec/parameter mismatch."""
    inputs = [Path(p).resolve() for p in args.inputs]
    for p in inputs:
        if not p.exists():
            sys.exit(f"Not found: {p}")
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                     delete=False) as tf:
        for p in inputs:
            # escape single quotes in path per ffmpeg concat demuxer rules
            safe = str(p).replace("'", r"'\''")
            tf.write(f"file '{safe}'\n")
        list_path = Path(tf.name)
    try:
        for p in inputs:
            print(f"  + {p.name}", file=sys.stderr)
        print(f"  → {out.name}", file=sys.stderr)
        copy_cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat",
                    "-safe", "0", "-i", str(list_path),
                    "-c", "copy", str(out)]
        try:
            run(copy_cmd)
            print("  (concatenated via -c copy, lossless)", file=sys.stderr)
        except subprocess.CalledProcessError:
            print("  -c copy failed (probably codec/param mismatch); "
                  "re-encoding...", file=sys.stderr)
            reencode = ["ffmpeg", "-y", "-v", "error", "-f", "concat",
                        "-safe", "0", "-i", str(list_path), str(out)]
            run(reencode)
            print("  (concatenated via re-encode)", file=sys.stderr)
    finally:
        list_path.unlink(missing_ok=True)
    print(str(out))


# ---------- CLI ----------

def main():
    p = argparse.ArgumentParser(prog="sync_trim", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="detect offsets, transcribe head/tail")
    a.add_argument("folder")
    a.add_argument("--primary", help="filename to use as primary timeline")
    a.add_argument("--head-seconds", type=float, default=60.0)
    a.add_argument("--tail-seconds", type=float, default=60.0)
    a.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"mlx-whisper model (default: {DEFAULT_MODEL})")
    a.add_argument("--words", action="store_true",
                   help="word-level timestamps (more precise, slightly slower)")
    a.set_defaults(func=cmd_analyze)

    pr = sub.add_parser("preview", help="render & play a 15s preview")
    pr.add_argument("folder")
    pr.add_argument("--start", type=float, required=True)
    pr.add_argument("--end", type=float, default=None,
                    help="optional end (preview is min(duration, end-start))")
    pr.add_argument("--duration", type=float, default=15.0)
    pr.add_argument("--audio-source", help="filename to mux audio from")
    pr.add_argument("--crop", action="append", help="FILE=W:H:X:Y (repeatable)")
    pr.add_argument("--no-play", action="store_true",
                    help="alias for --player none")
    pr.add_argument("--player", choices=["ffplay", "vlc", "none"],
                    default="ffplay",
                    help="how to play the preview (default: ffplay). VLC "
                         "matches QuickTime/YouTube color rendering more "
                         "closely than ffplay.")
    pr.add_argument("--polish-audio", action="store_true",
                    help="apply compressor + loudnorm (-16 LUFS) + limiter "
                         "to the muxed audio")
    pr.add_argument("--denoise", action="store_true",
                    help="apply afftdn FFT denoiser before polish "
                         "(removes steady-state hum / room tone)")
    pr.add_argument("--mute", action="append",
                    help="silence a time range (in primary's timeline). "
                         "Format: TS-TE, e.g. \"72:41-72:41.5\" or "
                         "\"4361-4361.5\". Repeatable.")
    pr.add_argument("--duck", action="append",
                    help="attenuate (not mute) a time range. Format: "
                         "TS-TE@DB where DB is negative dB, e.g. "
                         "\"3423.24-3424.43@-12\". Repeatable. Useful "
                         "for taming cough/laugh peaks adjacent to speech.")
    pr.add_argument("--cut", action="append",
                    help="excise a time range entirely (video + audio "
                         "skip past it). Format: TS-TE in primary's "
                         "timeline. Repeatable. Loudnorm sees post-cut "
                         "audio so levels stay consistent across the join.")
    pr.add_argument("--swap-channels", action="store_true",
                    help="swap stereo L/R channels (when the recorder put "
                         "the speakers on the wrong sides)")
    pr.add_argument("--fade-in", type=float, default=None,
                    help="audio fade-in duration in seconds at the start "
                         "of the trimmed window (applied after polish).")
    pr.add_argument("--fade-out", type=float, default=None,
                    help="audio fade-out duration in seconds, ending at "
                         "the end of the trimmed window (applied after "
                         "polish). Plan window length to include the fade.")
    pr.add_argument("--fade-out-curve", default="tri",
                    help="ffmpeg afade curve: tri (linear), log (steep "
                         "early drop, long quiet tail — hyperbolic feel), "
                         "exp, qsin, hsin, esin, cub, squ, cbr, par, ipar. "
                         "Default: tri.")
    pr.set_defaults(func=cmd_preview)

    r = sub.add_parser("render", help="produce trimmed masters + muxed output")
    r.add_argument("folder")
    r.add_argument("--start", type=float, required=True)
    r.add_argument("--end", type=float, required=True)
    r.add_argument("--audio-source", help="filename to mux audio from")
    r.add_argument("--crop", action="append", help="FILE=W:H:X:Y (repeatable)")
    r.add_argument("--outdir", help="output dir (default: <folder>/output)")
    r.add_argument("--keep-trimmed", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="keep per-file trimmed masters (default: yes; use "
                        "--no-keep-trimmed to delete after muxing)")
    r.add_argument("--accurate-trim", action="store_true",
                   help="re-encode trimmed masters for frame accuracy "
                        "(default uses -c copy, may shift up to 1s at cuts)")
    r.add_argument("--polish-audio", action="store_true",
                   help="apply compressor + loudnorm (-16 LUFS) + limiter "
                        "to the muxed output and audio-only masters")
    r.add_argument("--denoise", action="store_true",
                   help="apply afftdn FFT denoiser before polish "
                        "(removes steady-state hum / room tone)")
    r.add_argument("--mute", action="append",
                   help="silence a time range (in primary's timeline). "
                        "Format: TS-TE, e.g. \"72:41-72:41.5\". Repeatable.")
    r.add_argument("--duck", action="append",
                   help="attenuate (not mute) a time range. Format: "
                        "TS-TE@DB where DB is negative dB, e.g. "
                        "\"3423.24-3424.43@-12\". Repeatable.")
    r.add_argument("--cut", action="append",
                   help="excise a time range entirely (video + audio skip "
                        "past it). Format: TS-TE. Repeatable.")
    r.add_argument("--swap-channels", action="store_true",
                   help="swap stereo L/R channels")
    r.add_argument("--fade-in", type=float, default=None,
                   help="audio fade-in seconds at the start of the trim.")
    r.add_argument("--fade-out", type=float, default=None,
                   help="audio fade-out seconds, ending at end of the trim.")
    r.add_argument("--fade-out-curve", default="tri",
                   help="ffmpeg afade curve (default tri/linear). Use "
                        "'log' for steep early drop + quiet tail.")
    r.set_defaults(func=cmd_render)

    t = sub.add_parser("transcribe", help="transcribe an arbitrary time range")
    t.add_argument("folder", help="folder containing .audvid_state.json")
    t.add_argument("--file", help="filename within folder (default: primary)")
    t.add_argument("--start", type=float, default=0.0,
                   help="seconds (default: 0)")
    t.add_argument("--end", type=float, default=None,
                   help="seconds (default: file end)")
    t.add_argument("--model", default=DEFAULT_MODEL)
    t.add_argument("--words", action="store_true",
                   help="word-level timestamps")
    t.set_defaults(func=cmd_transcribe)

    s = sub.add_parser("stitch",
                       help="concatenate multiple rendered files into one")
    s.add_argument("-o", "--output", required=True,
                   help="output path (e.g. final.mp4)")
    s.add_argument("inputs", nargs="+",
                   help="input files in order (e.g. clip-A_synced.mp4 "
                        "clip-B_synced.mp4)")
    s.set_defaults(func=cmd_stitch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
