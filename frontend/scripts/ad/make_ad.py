#!/usr/bin/env python3
"""Turn the recorded product demo into a narrated video ad.

    python3 scripts/ad/make_ad.py DEMO.mp4 OUT.mp4

Inputs: the demo MP4 and its `.marks.json` (chapter start times, written
by scripts/app-demo/record-app-demo.mjs or
scripts/ad-routing/render.mjs). Adds, in order:

1. Voiceover: each line in script.json, spoken aloud and placed at its
   chapter, in sync with its subtitle. Two voices:
   - Kokoro (default): a natural neural voice that runs on this machine,
     no account needed. Install once, see kokoro_tts.cjs. AD_VOICE picks
     the speaker (default af_bella).
   - Google Cloud Text-to-Speech, used instead when GOOGLE_TTS_API_KEY
     is set (en-IN natural voices).
   A line that would not finish before the next one starts is spoken a
   little faster, never cut and never overlapped. With no voice
   available the ad is built with music and subtitles only, and says so.
2. Music: an original upbeat track, synthesised here from scratch, so
   there is no licence to worry about. It ducks under the voice.
3. Subtitles: every spoken line burned in, YouTube-ad style, with the
   key phrase picked out in the brand's orange.

Needs numpy and ffmpeg (with libass).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RATE = 48_000
CACHE = Path(tempfile.gettempdir()) / "ad-voice-cache"
# The lines to speak. AD_SCRIPT must point at the ad's script, e.g.
# scripts/ad-routing/script.json or scripts/app-demo/script.json.
if "AD_SCRIPT" not in os.environ:
    sys.exit("Set AD_SCRIPT to the ad's script.json, e.g. scripts/ad-routing/script.json")
SCRIPT = Path(os.environ["AD_SCRIPT"])


# --------------------------------------------------------------- timing


def load_lines(marks_path: Path) -> list[dict]:
    script = json.loads(SCRIPT.read_text())
    marks = {m["id"]: m["t"] for m in json.loads(marks_path.read_text())}
    marks["intro"] = 0.0
    lines = []
    for line in script["lines"]:
        if line["at"] not in marks:
            sys.exit(f"script.json refers to chapter '{line['at']}', which the recording does not have")
        lines.append({**line, "start": marks[line["at"]] + line["offset"]})
    return sorted(lines, key=lambda l: l["start"])


def plain(text: str) -> str:
    return text.replace("*", "")


# --------------------------------------------------------------- voice


def synthesize(text: str, voice: dict, key: str) -> np.ndarray:
    """One line of speech as mono float samples at RATE, cached by text."""
    digest = hashlib.sha256(json.dumps([text, voice]).encode()).hexdigest()[:20]
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"{digest}.wav"
    if not cached.exists():
        body = json.dumps(
            {
                "input": {"text": text},
                "voice": {"languageCode": voice["languageCode"], "name": voice["name"]},
                "audioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": RATE,
                    "speakingRate": voice.get("speakingRate", 1.0),
                    "pitch": voice.get("pitch", 0.0),
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URL
            cached.write_bytes(base64.b64decode(json.loads(response.read())["audioContent"]))
    with wave.open(str(cached)) as w:
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return frames.astype(np.float32) / 32768.0


KOKORO = HERE / "kokoro_tts.cjs"
KOKORO_MODEL = HERE / ".voice" / "node_modules" / "n8n-nodes-ttsbro" / "kokoro-int8-en-v0_19"


def decode(path: Path) -> np.ndarray:
    """Any audio file as mono float samples at RATE (ffmpeg resamples)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def tidy(clip: np.ndarray) -> np.ndarray:
    """Trim the model's leading and trailing silence, and even out levels
    so every line sits at the same loudness."""
    loud = np.flatnonzero(np.abs(clip) > 0.015)
    if len(loud):
        pad = int(0.04 * RATE)
        clip = clip[max(0, loud[0] - pad) : loud[-1] + pad]
    rms = float(np.sqrt(np.mean(clip**2))) or 1.0
    return clip * (0.1 / rms)


def kokoro_clips(texts: list[str], speeds: list[float], voice: str) -> list[np.ndarray]:
    work = Path(tempfile.mkdtemp(prefix="voice-"))
    items = [
        {"text": t, "voice": voice, "speed": round(sp, 3), "out": str(work / f"{i}.wav")}
        for i, (t, sp) in enumerate(zip(texts, speeds, strict=True))
    ]
    (work / "jobs.json").write_text(json.dumps({"items": items}))
    subprocess.run(["node", str(KOKORO), str(work / "jobs.json")], check=True, capture_output=True)
    return [tidy(decode(Path(it["out"]))) for it in items]


def voice_track(lines: list[dict], duration: float) -> tuple[np.ndarray, str] | None:
    key = os.environ.get("GOOGLE_TTS_API_KEY")
    texts = [plain(line["text"]) for line in lines]

    # How long each line may last: until just before the next one starts.
    windows = []
    for i, line in enumerate(lines):
        until = lines[i + 1]["start"] - 0.25 if i + 1 < len(lines) else duration - 0.4
        windows.append(until - line["start"])

    if key:
        voice = json.loads(SCRIPT.read_text())["voice"]
        voice["name"] = os.environ.get("GOOGLE_TTS_VOICE", voice["name"])
        clips = [tidy(synthesize(t, voice, key)) for t in texts]
        label = f"Google {voice['name']}"
    elif KOKORO_MODEL.exists():
        name = os.environ.get("AD_VOICE", "af_bella")
        base = float(os.environ.get("AD_VOICE_SPEED", "0.93"))
        # A line may set its own "pace" in script.json, relative to the base.
        clips = kokoro_clips(texts, [base * line.get("pace", 1.0) for line in lines], name)
        # Any line too long for its window is re-spoken a touch faster,
        # so it ends with its subtitle instead of running into the next.
        slow = [i for i, c in enumerate(clips) if len(c) / RATE > windows[i]]
        if slow:
            again = kokoro_clips(
                [texts[i] for i in slow],
                [min(1.3, base * lines[i].get("pace", 1.0) * (len(clips[i]) / RATE) / windows[i] * 1.04) for i in slow],
                name,
            )
            for i, clip in zip(slow, again, strict=True):
                clips[i] = clip
        label = f"Kokoro {name}"
    else:
        return None

    track = np.zeros(int(duration * RATE) + RATE, dtype=np.float32)
    for line, clip, window in zip(lines, clips, windows, strict=True):
        if len(clip) / RATE > window + 0.05:
            print(f"warning: '{plain(line['text'])[:40]}…' runs {len(clip) / RATE - window:.2f}s past its window")
        line["end"] = line["start"] + len(clip) / RATE
        i = int(line["start"] * RATE)
        track[i : i + len(clip)] += clip[: len(track) - i]
    return track[: int(duration * RATE)], label


def estimate_ends(lines: list[dict]) -> None:
    """Without a voice, time subtitles at a natural speaking pace."""
    for i, line in enumerate(lines):
        words = len(plain(line["text"]).split())
        end = line["start"] + 0.45 + words * 0.36
        if i + 1 < len(lines):
            end = min(end, lines[i + 1]["start"] - 0.1)
        line["end"] = end


# --------------------------------------------------------------- music


def note(n: int) -> float:
    """MIDI note number to frequency."""
    return 440.0 * 2 ** ((n - 69) / 12)


def lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """One-pole low-pass; cutoff may sweep over time."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=np.float32), x.shape)
    alpha = 1 - np.exp(-2 * np.pi * cutoff / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):  # pure python is fine for a minute of audio
        acc += alpha[i] * (x[i] - acc)
        y[i] = acc
    return y


def music(duration: float) -> np.ndarray:
    """An upbeat tech bed: pad, plucked arpeggio, bass, soft drums.

    vi–IV–I–V in A major at 112 bpm. The drums enter after the intro
    and drop out for the final card, and everything fades at the end.
    """
    rng = np.random.default_rng(7)
    bpm = 112
    beat = 60 / bpm
    n = int(duration * RATE)
    t = np.arange(n) / RATE
    out = np.zeros((n, 2), dtype=np.float32)

    # F#m, D, A, E: one chord per bar.
    chords = [[54, 57, 61, 66], [50, 54, 57, 62], [57, 61, 64, 69], [52, 56, 59, 64]]
    bar = beat * 4

    def chord_at(time: float) -> list[int]:
        return chords[int(time // bar) % 4]

    # Pad: detuned saw-ish stack, slowly opening filter.
    pad = np.zeros(n, dtype=np.float32)
    for b in range(int(duration // bar) + 1):
        s, e = int(b * bar * RATE), min(n, int((b + 1) * bar * RATE))
        if s >= n:
            break
        seg = t[s:e]
        for m in chords[b % 4]:
            f = note(m - 12)
            for detune in (-0.12, 0.0, 0.11):
                ph = 2 * np.pi * f * (1 + detune / 100) * seg
                pad[s:e] += (np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.15 * np.sin(3 * ph)) * 0.05
        fade = np.minimum(1, np.minimum((seg - seg[0]) / 0.25, (seg[-1] - seg + 1e-3) / 0.25))
        pad[s:e] *= fade
    sweep = 500 + 2600 * np.clip(t / 6, 0, 1)
    pad = lowpass(pad, sweep)

    # Arpeggio: sixteenths through the chord, plucked, with an echo.
    arp = np.zeros(n, dtype=np.float32)
    step = beat / 4
    pattern = [0, 1, 2, 3, 2, 1, 2, 3]
    for k in range(int(duration / step)):
        start = k * step
        m = chord_at(start)[pattern[k % len(pattern)]] + 12
        length = int(0.22 * RATE)
        s = int(start * RATE)
        seg_t = np.arange(min(length, n - s)) / RATE
        tone = np.sin(2 * np.pi * note(m) * seg_t) + 0.3 * np.sin(2 * np.pi * 2 * note(m) * seg_t)
        env = np.exp(-seg_t * 16)
        arp[s : s + len(seg_t)] += (tone * env * (0.10 if k % 4 == 0 else 0.075)).astype(np.float32)
    delay = int(beat * 0.75 * RATE)
    arp_echo = np.zeros_like(arp)
    arp_echo[delay:] = arp[:-delay] * 0.35

    # Bass: eighth-note pulses on the root.
    bass = np.zeros(n, dtype=np.float32)
    for k in range(int(duration / (beat / 2))):
        start = k * beat / 2
        f = note(chord_at(start)[0] - 24)
        s = int(start * RATE)
        seg_t = np.arange(min(int(beat / 2 * RATE), n - s)) / RATE
        env = np.minimum(1, seg_t / 0.005) * np.exp(-seg_t * 5)
        bass[s : s + len(seg_t)] += ((np.sin(2 * np.pi * f * seg_t) + 0.2 * np.sin(4 * np.pi * f * seg_t)) * env * 0.22).astype(np.float32)

    # Drums, from bar 2 until the last two bars.
    drums = np.zeros(n, dtype=np.float32)
    drum_from, drum_to = 2 * bar, duration - 2 * bar
    for k in range(int(duration / beat)):
        start = k * beat
        if not drum_from <= start < drum_to:
            continue
        s = int(start * RATE)
        seg_t = np.arange(min(int(0.3 * RATE), n - s)) / RATE
        kick = np.sin(2 * np.pi * (48 + 110 * np.exp(-seg_t * 30)) * seg_t) * np.exp(-seg_t * 9) * 0.45
        drums[s : s + len(seg_t)] += kick.astype(np.float32)
        if k % 2 == 1:  # clap on 2 and 4
            noise = rng.standard_normal(len(seg_t)).astype(np.float32)
            clap = np.diff(noise, prepend=0) * np.exp(-seg_t * 22) * 0.07
            drums[s : s + len(seg_t)] += clap
        for half in (0.0, 0.5):  # closed hats on eighths
            hs = int((start + half * beat) * RATE)
            ht = np.arange(min(int(0.05 * RATE), n - hs)) / RATE
            if len(ht) <= 0:
                continue
            hat = np.diff(rng.standard_normal(len(ht)).astype(np.float32), prepend=0)
            drums[hs : hs + len(ht)] += hat * np.exp(-ht * 70) * 0.03

    # Take the fizz off the cymbals: nothing above ~8 kHz is needed.
    drums = lowpass(drums, 8000.0)

    # Mix with a little stereo width: arp and echo opposite sides.
    out[:, 0] = pad + bass + drums + arp * 0.8 + arp_echo * 1.1
    out[:, 1] = pad + bass + drums + arp * 1.1 + arp_echo * 0.8

    # Fade in, fade out.
    gain = np.minimum(1, t / 1.2) * np.clip((duration - t) / 3.0, 0, 1)
    out *= gain[:, None]
    out /= max(1e-6, np.abs(out).max()) / 0.8
    return out


# --------------------------------------------------------------- subtitles


def ass_time(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def subtitles(lines: list[dict], path: Path) -> None:
    """Bottom-centre captions in a dark box, key phrase in orange."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Line,DM Sans,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H26150C07,0,0,0,0,100,100,0,0,4,16,0,2,300,300,64,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for line in lines:
        parts = line["text"].split("*")
        # Odd parts sit between asterisks: the phrase to pick out.
        text = "".join(
            f"{{\\c&H4C8AFF&}}{p}{{\\c&HFFFFFF&}}" if i % 2 else p for i, p in enumerate(parts)
        )
        events.append(
            f"Dialogue: 0,{ass_time(line['start'])},{ass_time(line['end'] + 0.25)},Line,,0,0,0,,"
            f"{{\\fad(180,180)}}{text}"
        )
    path.write_text(header + "\n".join(events) + "\n")


# --------------------------------------------------------------- assemble


def write_wav(path: Path, samples: np.ndarray) -> None:
    data = np.clip(samples, -1, 1)
    if data.ndim == 1:
        data = data[:, None]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((data * 32767).astype(np.int16).tobytes())


def duration_of(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def loudness(path: Path) -> float:
    report = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-map", "0:a", "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    summary = report[report.rfind("Summary:") :]
    return float(summary.split("I:")[1].split("LUFS")[0])


def level(path: Path, target: float = -16.0) -> None:
    """Bring the whole ad to a standard online loudness with one fixed
    gain, which keeps the balance between voice and music as mixed."""
    gain = target - loudness(path)
    if abs(gain) < 0.5:
        return
    tmp = path.with_suffix(".tmp.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-c:v", "copy",
         "-af", f"volume={gain:.2f}dB,alimiter=limit=0.75:level=false",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(RATE), "-movflags", "+faststart", str(tmp)],
        check=True,
    )
    tmp.replace(path)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    video, out = Path(sys.argv[1]), Path(sys.argv[2])
    marks = video.with_suffix(".marks.json")
    duration = duration_of(video)
    lines = load_lines(marks)

    work = Path(tempfile.mkdtemp(prefix="ad-"))
    spoken = voice_track(lines, duration)
    voice = spoken[0] if spoken else None
    if spoken is None:
        estimate_ends(lines)
        print("No voice available (no Google key, no local Kokoro model): music and subtitles only.")
    else:
        write_wav(work / "voice.wav", spoken[0])
        print(f"Voiceover: {spoken[1]}")
    write_wav(work / "music.wav", music(duration))
    subtitles(lines, work / "subs.ass")

    fonts = HERE / "fonts"
    video_filter = f"[0:v]ass={work / 'subs.ass'}:fontsdir={fonts}[v]"
    if voice is not None:
        # The voice pushes the music down while it speaks, then lets it back up.
        audio = (
            # Music sits well under the voice and dips further while she
            # speaks; a limiter, not a normaliser, so the voice stays on top.
            "[1:a]volume=0.32[m];"
            "[2:a]aformat=channel_layouts=stereo,highpass=f=80,"
            "acompressor=threshold=0.12:ratio=3:attack=5:release=150:makeup=1.4,volume=1.5,asplit=2[vk][vm];"
            "[m][vk]sidechaincompress=threshold=0.012:ratio=14:attack=10:release=550[duck];"
            "[duck][vm]amix=inputs=2:normalize=0,alimiter=limit=0.75:level=false[a]"
        )
        inputs = ["-i", str(video), "-i", str(work / "music.wav"), "-i", str(work / "voice.wav")]
    else:
        audio = "[1:a]volume=0.8,loudnorm=I=-18:TP=-1.5:LRA=11[a]"
        inputs = ["-i", str(video), "-i", str(work / "music.wav")]

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", f"{video_filter};{audio}",
         "-map", "[v]", "-map", "[a]",
         # AD_CRF trades size for detail: a long film of app screens
         # stays under ~15 MB at 30.
         "-c:v", "libx264", "-preset", "slow", "-crf", os.environ.get("AD_CRF", "18"), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(RATE),
         "-movflags", "+faststart", "-shortest", str(out)],
        check=True,
    )
    level(out)
    (out.with_suffix(".srt")).write_text(
        "\n".join(
            f"{i}\n{srt_time(l['start'])} --> {srt_time(l['end'])}\n{plain(l['text'])}\n"
            for i, l in enumerate(lines, 1)
        )
    )
    print(f"{out} · {duration:.1f}s · voice: {'yes' if voice is not None else 'no'}")


if __name__ == "__main__":
    main()
