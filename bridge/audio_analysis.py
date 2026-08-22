"""Audio analysis and digital signal processing utilities for DaVinci Resolve AI Bridge."""

import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_audio_temp_dir() -> Path:
    """Return a temporary directory for audio extraction."""
    audio_dir = Path(tempfile.gettempdir()) / "resolve-audio-analysis"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def extract_media_audio(source_media_path: str, output_wav_path: Path, sample_rate: int = 48000) -> bool:
    """Extract audio from a video or audio file to a standard 16-bit PCM WAV file."""
    source_p = Path(source_media_path)
    if not source_p.exists():
        return False

    # 1. If already a WAV file, copy or verify directly
    if source_p.suffix.lower() == ".wav":
        try:
            with wave.open(str(source_p), "rb") as wf:
                if wf.getnchannels() > 0:
                    shutil.copy2(str(source_p), str(output_wav_path))
                    return True
        except Exception:
            pass

    # 2. macOS built-in afconvert (fast, hardware-accelerated, zero dependencies)
    afconvert_bin = shutil.which("afconvert")
    if afconvert_bin:
        cmd = [
            afconvert_bin,
            "-f",
            "WAVE",
            "-d",
            "LEI16@48000",
            "-c",
            "2",
            str(source_media_path),
            str(output_wav_path),
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0 and output_wav_path.exists() and output_wav_path.stat().st_size > 44:
            return True

    # 3. ffmpeg fallback if present
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source_media_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            str(sample_rate),
            "-f",
            "wav",
            str(output_wav_path),
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0 and output_wav_path.exists() and output_wav_path.stat().st_size > 44:
            return True

    return False


def _read_wav_samples(wav_path: Path, start_sec: float = 0.0, duration_sec: Optional[float] = None):
    """Read 16-bit PCM samples as a normalized mono float list."""
    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        total_frames = wf.getnframes()

        start_frame = max(0, int(start_sec * sample_rate))
        if start_frame >= total_frames:
            return [], sample_rate, channels, total_frames / float(sample_rate)

        if duration_sec is not None and duration_sec > 0:
            frames_to_read = min(int(duration_sec * sample_rate), total_frames - start_frame)
        else:
            frames_to_read = total_frames - start_frame

        wf.setpos(start_frame)
        raw_bytes = wf.readframes(frames_to_read)

    num_samples = len(raw_bytes) // (2 * channels)
    if num_samples == 0:
        return [], sample_rate, channels, 0.0

    # Unpack int16 samples
    fmt = f"<{num_samples * channels}h"
    raw_ints = struct.unpack(fmt, raw_bytes)

    # Convert to mono normalized float [-1.0, 1.0]
    if channels == 1:
        samples = [s / 32768.0 for s in raw_ints]
    else:
        # Average stereo channels to mono
        samples = [
            ((raw_ints[i * 2] + raw_ints[i * 2 + 1]) / 2.0) / 32768.0
            for i in range(num_samples)
        ]

    total_duration = total_frames / float(sample_rate)
    return samples, sample_rate, channels, total_duration


def analyze_audio_loudness(
    wav_path: Path, start_sec: float = 0.0, duration_sec: Optional[float] = None
) -> Dict[str, Any]:
    """Compute overall loudness metrics (Peak dBFS, RMS dBFS, clipping detection)."""
    samples, sample_rate, channels, total_duration = _read_wav_samples(wav_path, start_sec, duration_sec)
    if not samples:
        return {
            "duration_sec": 0.0,
            "peak_dbfs": -100.0,
            "rms_dbfs": -100.0,
            "is_clipping": False,
            "sample_rate": sample_rate,
            "channels": channels,
        }

    peak_val = max(abs(s) for s in samples)
    sum_sq = sum(s * s for s in samples)
    rms_val = math.sqrt(sum_sq / len(samples))

    peak_db = 20.0 * math.log10(max(1e-6, peak_val))
    rms_db = 20.0 * math.log10(max(1e-6, rms_val))

    return {
        "duration_sec": round(len(samples) / float(sample_rate), 3),
        "peak_dbfs": round(peak_db, 2),
        "rms_dbfs": round(rms_db, 2),
        "is_clipping": bool(peak_db >= -0.05),
        "sample_rate": sample_rate,
        "channels": channels,
    }


def detect_silence_intervals(
    wav_path: Path,
    silence_threshold_db: float = -40.0,
    min_silence_duration: float = 0.3,
    start_sec: float = 0.0,
    duration_sec: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Detect dead-air / silent intervals for automated jump-cuts."""
    samples, sample_rate, channels, _ = _read_wav_samples(wav_path, start_sec, duration_sec)
    if not samples:
        return []

    window_size = int(sample_rate * 0.05)  # 50ms windows
    if window_size <= 0:
        return []

    num_windows = len(samples) // window_size
    silent_windows = []

    for i in range(num_windows):
        chunk = samples[i * window_size : (i + 1) * window_size]
        chunk_rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
        chunk_db = 20.0 * math.log10(max(1e-6, chunk_rms))
        silent_windows.append(chunk_db <= silence_threshold_db)

    # Group continuous silent windows into intervals
    intervals = []
    in_silence = False
    interval_start = 0.0

    for i, is_silent in enumerate(silent_windows):
        current_time = start_sec + (i * 0.05)
        if is_silent and not in_silence:
            in_silence = True
            interval_start = current_time
        elif not is_silent and in_silence:
            in_silence = False
            duration = current_time - interval_start
            if duration >= min_silence_duration:
                intervals.append({
                    "start_sec": round(interval_start, 3),
                    "end_sec": round(current_time, 3),
                    "duration_sec": round(duration, 3),
                })

    if in_silence:
        end_time = start_sec + (num_windows * 0.05)
        duration = end_time - interval_start
        if duration >= min_silence_duration:
            intervals.append({
                "start_sec": round(interval_start, 3),
                "end_sec": round(end_time, 3),
                "duration_sec": round(duration, 3),
            })

    return intervals


def compute_energy_envelope(
    wav_path: Path,
    window_sec: float = 0.05,
    start_sec: float = 0.0,
    duration_sec: Optional[float] = None,
) -> List[Dict[str, float]]:
    """Compute time-series RMS loudness envelope for beat sync and animation timing."""
    samples, sample_rate, _, _ = _read_wav_samples(wav_path, start_sec, duration_sec)
    if not samples:
        return []

    window_size = max(1, int(sample_rate * window_sec))
    num_windows = len(samples) // window_size
    envelope = []

    for i in range(num_windows):
        chunk = samples[i * window_size : (i + 1) * window_size]
        chunk_rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
        chunk_db = 20.0 * math.log10(max(1e-6, chunk_rms))
        envelope.append({
            "time_sec": round(start_sec + (i * window_sec), 3),
            "rms_dbfs": round(chunk_db, 1),
        })

    return envelope


def detect_acoustic_onsets(
    wav_path: Path,
    start_sec: float = 0.0,
    duration_sec: Optional[float] = None,
    lead_offset_ms: float = 120.0,
) -> List[float]:
    """Detect transient speech onsets using high-frequency energy derivative (spectral flux proxy)."""
    samples, sample_rate, _, _ = _read_wav_samples(wav_path, start_sec, duration_sec)
    if not samples:
        return []

    window_size = int(sample_rate * 0.01)  # 10ms windows
    if window_size <= 0:
        return []

    num_windows = len(samples) // window_size
    energies = []
    for i in range(num_windows):
        chunk = samples[i * window_size : (i + 1) * window_size]
        e = sum(s * s for s in chunk)
        energies.append(e)

    onsets = []
    lead_sec = lead_offset_ms / 1000.0
    for i in range(1, len(energies) - 1):
        diff = energies[i] - energies[i - 1]
        if diff > 0.05 and energies[i] > 0.01:
            t = start_sec + (i * 0.01) - lead_sec
            onsets.append(round(max(0.0, t), 3))

    return onsets


def apply_lead_compensation(
    segments: List[Dict[str, Any]],
    lead_offset_ms: float = 120.0,
    fps: float = 24.0,
) -> List[Dict[str, Any]]:
    """Apply negative latency / lead offset to word/syllable timestamps to eliminate perceptual lag."""
    lead_sec = lead_offset_ms / 1000.0
    lead_frames = int(round((lead_offset_ms / 1000.0) * fps))

    adjusted = []
    for seg in segments:
        new_seg = dict(seg)
        if "start_sec" in new_seg:
            new_seg["start_sec"] = max(0.0, round(new_seg["start_sec"] - lead_sec, 3))
        if "start_frame" in new_seg:
            new_seg["start_frame"] = max(0, new_seg["start_frame"] - lead_frames)
        if "end_sec" in new_seg:
            new_seg["end_sec"] = max(new_seg.get("start_sec", 0.0), round(new_seg["end_sec"] - (lead_sec * 0.5), 3))
        if "end_frame" in new_seg:
            new_seg["end_frame"] = max(new_seg.get("start_frame", 0), new_seg["end_frame"] - max(1, lead_frames // 2))
        adjusted.append(new_seg)

    return adjusted

