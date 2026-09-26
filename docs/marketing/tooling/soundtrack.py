"""Synthesize the promo's soundtrack (48 kHz stereo WAV), cue-locked to
stage.html's beat sheet. Pure numpy, no samples, so there is nothing to
license: warm pad chords, a soft pulse under the app scenes, a pluck
arpeggio through the session scene, UI ticks on every on-screen tap,
air whooshes on scene changes and a resolving chord under the end card.

    python docs/marketing/tooling/soundtrack.py OUT.wav
"""

import argparse
import wave
from pathlib import Path

import numpy as np

SR = 48_000
DURATION = 18.5
BPM = 120
BEAT = 60 / BPM

# Cue points (seconds) shared with stage.html.
LOGO_DOT = 0.85
PHONE_IN = 2.45
TRANSITIONS = [2.45, 5.45, 7.72, 9.3, 11.0, 14.95]
TAPS = [5.3, 6.25, 6.7, 7.15, 7.62, 8.55, 9.2]
END_CARD = 15.95

NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name: str) -> float:
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((NOTE[pitch] + 12 * (octave + 1) - 69) / 12)


CHORDS = [  # (start, end, notes)
    (0.0, 4.4, ["A2", "E3", "G3", "B3", "C4"]),  # Am9
    (4.4, 8.4, ["F2", "C3", "E3", "G3", "A3"]),  # Fmaj9
    (8.4, 11.0, ["C3", "G3", "B3", "D4", "E4"]),  # Cmaj9
    (11.0, 14.95, ["G2", "D3", "E3", "B3", "D4"]),  # G6
    (14.95, 15.95, ["F2", "C3", "E3", "G3", "A3"]),  # Fmaj9
    (15.95, DURATION, ["C2", "G2", "E3", "B3", "D4", "G4"]),  # Cmaj9, the landing
]

t = np.arange(int(SR * DURATION)) / SR


def env(start: float, end: float, attack: float, release: float) -> np.ndarray:
    e = np.clip((t - start) / attack, 0, 1) * np.clip((end - t) / release, 0, 1)
    return np.where((t >= start) & (t <= end), e, 0.0) ** 1.5


def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spectrum *= 1 / np.sqrt(1 + (freqs / cutoff) ** 4)
    return np.fft.irfft(spectrum, len(x))


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spectrum *= 1 / np.sqrt(1 + (cutoff / np.maximum(freqs, 1)) ** 4)
    return np.fft.irfft(spectrum, len(x))


def pad() -> np.ndarray:
    out = np.zeros((2, len(t)))
    for start, end, notes in CHORDS:
        overlap = 0.35
        e = env(start - overlap, end + overlap, 0.6 if start else 1.4, 0.7)
        for note in notes:
            f = hz(note)
            for ch, detune in enumerate((-0.11, 0.13)):
                voice = np.zeros(len(t))
                for n in range(1, 7):  # soft saw: a few harmonics
                    voice += np.sin(2 * np.pi * f * n * (1 + detune / 100) * t + n * 0.7) / n**1.6
                out[ch] += voice * e / len(notes)
    # breathe: slow filter-like swell by mixing a darker copy
    for ch in range(2):
        out[ch] = highpass(lowpass(out[ch], 2600), 110)
    return out * 0.3


def pulse() -> np.ndarray:
    out = np.zeros(len(t))
    beat = PHONE_IN
    while beat < 14.9:
        k = t - beat
        m = (k >= 0) & (k < 0.4)
        f = 48 + 70 * np.exp(-k[m] * 38)
        phase = 2 * np.pi * np.cumsum(f) / SR
        out[m] += np.sin(phase) * np.exp(-k[m] * 9) * 0.9
        beat += BEAT
    rng = np.random.default_rng(3)
    hats = np.zeros(len(t))
    off = PHONE_IN + 2 * BEAT + BEAT / 2
    while off < 14.9:
        k = t - off
        m = (k >= 0) & (k < 0.08)
        hats[m] += rng.standard_normal(m.sum()) * np.exp(-k[m] * 70)
        off += BEAT
    out += highpass(hats, 6000) * 0.6
    return out


def pluck(freq: float, start: float, length: float = 0.5, bright: float = 1.0) -> np.ndarray:
    k = t - start
    m = (k >= 0) & (k < length)
    x = np.zeros(len(t))
    kk = k[m]
    tone = sum(np.sin(2 * np.pi * freq * n * kk) * bright**n / n**1.2 for n in range(1, 5))
    x[m] = tone * np.exp(-kk * 11) * np.clip(kk / 0.003, 0, 1)
    return x


def arpeggio() -> np.ndarray:
    out = np.zeros(len(t))
    step = BEAT / 2
    s, i = 5.9, 0
    while s < 10.9:
        notes = next(n for a, b, n in CHORDS if a <= s < b)
        tones = [hz(n) * 2 for n in notes[1:]]
        order = [0, 2, 1, 3, 2, 1]
        out += pluck(tones[order[i % len(order)] % len(tones)], s, 0.45, 0.62) * 0.26
        s += step
        i += 1
    return out


def shimmer() -> np.ndarray:
    """High, slow-attack chord tones over the end card: the "lift"."""
    out = np.zeros((2, len(t)))
    e = env(END_CARD - 0.4, DURATION, 1.2, 2.0)
    for i, note in enumerate(["E5", "G5", "B5", "D6"]):
        f = hz(note)
        for ch in range(2):
            wobble = 1 + 0.004 * np.sin(2 * np.pi * (0.3 + 0.1 * i + 0.05 * ch) * t)
            out[ch] += np.sin(2 * np.pi * f * wobble * t) * e * 0.05
    return out


def ticks() -> np.ndarray:
    out = np.zeros(len(t))
    scale = [hz(n) for n in ["E5", "G5", "A5", "B5", "D6", "E6", "G6"]]
    for i, tap in enumerate(TAPS):
        f = scale[i % len(scale)]
        k = t - tap
        m = (k >= 0) & (k < 0.12)
        out[m] += np.sin(2 * np.pi * f * k[m]) * np.exp(-k[m] * 60) * 0.35
        # the "thock" of a finger on glass
        m2 = (k >= 0) & (k < 0.03)
        out[m2] += np.sin(2 * np.pi * 180 * k[m2]) * np.exp(-k[m2] * 160) * 0.5
    return out


def whooshes() -> np.ndarray:
    rng = np.random.default_rng(11)
    noise = rng.standard_normal(len(t))
    noise = highpass(lowpass(noise, 4000), 300)
    out = np.zeros(len(t))
    for c in TRANSITIONS:
        rise, fall = 0.35, 0.45
        e = np.clip((t - (c - rise)) / rise, 0, 1) ** 2 * np.clip(((c + fall) - t) / fall, 0, 1) ** 2
        out += noise * e * 0.1
    return out


def logo_hit() -> np.ndarray:
    out = np.zeros(len(t))
    for note, gain in (("A4", 0.5), ("E5", 0.35), ("A5", 0.2)):
        out += pluck(hz(note), LOGO_DOT, 2.4, 0.3) * gain
    k = t - LOGO_DOT
    m = (k >= 0) & (k < 1.2)
    out[m] += np.sin(2 * np.pi * 55 * k[m]) * np.exp(-k[m] * 4.5) * 0.25
    for note, gain in (("C5", 0.35), ("G5", 0.25), ("E6", 0.12)):
        out += pluck(hz(note), END_CARD, 2.5, 0.3) * gain
    return out


def reverb(x: np.ndarray, seconds: float = 2.2, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 3.2)
    ir = lowpass(np.concatenate([ir, np.zeros(len(x) - n)]), 5000)[:n]
    size = len(x) + n
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return wet / np.max(np.abs(wet)) * np.max(np.abs(x))


def mix() -> np.ndarray:
    p = pad()
    mono_fx = arpeggio() + ticks() + logo_hit()
    kick = highpass(pulse(), 45) * 0.24
    air = whooshes()
    left = p[0] + kick + mono_fx * 0.95 + air
    right = p[1] + kick + mono_fx * 1.0 + air
    stereo = np.stack([left, right]) + shimmer()
    wet = np.stack([reverb(stereo[0], seed=5), reverb(stereo[1], seed=6)])
    out = stereo * 0.8 + wet * 0.32
    # master: fade in/out, gentle saturation, normalise to -1 dBFS
    master = np.clip(t / 0.3, 0, 1) * np.clip((DURATION - t) / 1.6, 0, 1)
    out *= master
    return out / np.max(np.abs(out)) * 10 ** (-3 / 20)


def loudnorm(path: Path, target: float = -16.0) -> None:
    """Two-pass EBU R128 normalisation (linear gain, -1.5 dBTP ceiling)."""
    import json
    import subprocess

    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    spec = f"loudnorm=I={target}:TP=-1.5:LRA=11"
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", spec + ":print_format=json", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    m = json.loads(probe[probe.rindex("{") : probe.rindex("}") + 1])
    tmp = path.with_suffix(".norm.wav")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-af",
            f"{spec}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true",
            "-ar",
            str(SR),
            str(tmp),
        ],
        check=True,
    )
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    audio = mix()
    pcm = (audio.T * 32767).astype("<i2")
    with wave.open(str(args.out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    loudnorm(args.out)


if __name__ == "__main__":
    main()
