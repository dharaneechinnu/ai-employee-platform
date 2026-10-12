#!/usr/bin/env python3
"""Turn the recorded product demo into a narrated video ad.

    python3 scripts/ad/make_ad.py DEMO.mp4 OUT.mp4

Inputs: the demo MP4 and its `.marks.json` (chapter start times, written
by record-demo.mjs). Adds, in order:

1. Voiceover: each line in script.json, spoken by a Google Cloud
   Text-to-Speech natural voice and placed at its chapter. Needs the
   GOOGLE_TTS_API_KEY environment variable; without it the ad is built
   with music and subtitles only, and says so.
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


# --------------------------------------------------------------- timing


def load_lines(marks_path: Path) -> list[dict]:
    script = json.loads((HERE / "script.json").read_text())
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


def voice_track(lines: list[dict], duration: float) -> np.ndarray | None:
    key = os.environ.get("GOOGLE_TTS_API_KEY")
    if not key:
        return None
    voice = json.loads((HERE / "script.json").read_text())["voice"]
    voice["name"] = os.environ.get("GOOGLE_TTS_VOICE", voice["name"])
    track = np.zeros(int(duration * RATE) + RATE, dtype=np.float32)
    cursor = 0.0
    for line in lines:
        clip = synthesize(plain(line["text"]), voice, key)
        # Never let two lines talk over each other: a line that would
        # start before the previous one ends waits for it.
        start = max(line["start"], cursor + 0.15)
        line["start"] = start
        line["end"] = start + len(clip) / RATE
        cursor = line["end"]
        i = int(start * RATE)
        track[i : i + len(clip)] += clip[: len(track) - i]
    return track[: int(duration * RATE)]


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


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    video, out = Path(sys.argv[1]), Path(sys.argv[2])
    marks = video.with_suffix(".marks.json")
    duration = duration_of(video)
    lines = load_lines(marks)

    work = Path(tempfile.mkdtemp(prefix="ad-"))
    voice = voice_track(lines, duration)
    if voice is None:
        estimate_ends(lines)
        print("GOOGLE_TTS_API_KEY is not set: building with music and subtitles only, no voiceover.")
    else:
        write_wav(work / "voice.wav", voice)
    write_wav(work / "music.wav", music(duration))
    subtitles(lines, work / "subs.ass")

    fonts = HERE / "fonts"
    video_filter = f"[0:v]ass={work / 'subs.ass'}:fontsdir={fonts}[v]"
    if voice is not None:
        # The voice pushes the music down while it speaks, then lets it back up.
        audio = (
            "[1:a]volume=0.55[m];[2:a]aformat=channel_layouts=stereo,volume=1.6,asplit=2[vk][vm];"
            "[m][vk]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450[duck];"
            "[duck][vm]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        )
        inputs = ["-i", str(video), "-i", str(work / "music.wav"), "-i", str(work / "voice.wav")]
    else:
        audio = "[1:a]volume=0.8,loudnorm=I=-18:TP=-1.5:LRA=11[a]"
        inputs = ["-i", str(video), "-i", str(work / "music.wav")]

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", f"{video_filter};{audio}",
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(RATE),
         "-movflags", "+faststart", "-shortest", str(out)],
        check=True,
    )
    (out.with_suffix(".srt")).write_text(
        "\n".join(
            f"{i}\n{srt_time(l['start'])} --> {srt_time(l['end'])}\n{plain(l['text'])}\n"
            for i, l in enumerate(lines, 1)
        )
    )
    print(f"{out} · {duration:.1f}s · voice: {'yes' if voice is not None else 'no'}")


if __name__ == "__main__":
    main()
