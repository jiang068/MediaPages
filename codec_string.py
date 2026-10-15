"""RFC 6381 codec strings for HLS/fMP4 assets.

Ported from the EVA site build, where the strings were needed for two things:

* ``#EXT-X-STREAM-INF:CODECS="..."`` in master playlists
* ``MediaSource.isTypeSupported('video/mp4; codecs="..."')`` before handing a
  stream to hls.js

Only the init segment is inspected; the media segments repeat the same codec
configuration. Stream-copied MP4/MKV is supported, so no re-encode is needed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class CodecProbeError(RuntimeError):
    """Raised when a codec string cannot be derived from an init segment."""


def _resolve_ffprobe(ffprobe: str | None = None) -> str:
    if ffprobe:
        return ffprobe
    found = shutil.which("ffprobe")
    if not found:
        raise CodecProbeError("ffprobe was not found on PATH")
    return found


def probe_codec_string(init_segment: str | Path, ffprobe: str | None = None) -> str:
    """Return a comma-separated RFC 6381 codec string for an fMP4 init segment."""
    executable = _resolve_ffprobe(ffprobe)
    command = [
        executable, "-v", "fatal",
        "-show_streams", "-show_data", "-of", "json",
        str(init_segment),
    ]
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
        data = json.loads(output)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as error:
        raise CodecProbeError(f"unable to probe {init_segment}: {error}") from error

    values: list[str] = []
    for stream in data.get("streams", []):
        name = stream.get("codec_name")
        if name == "aac":
            values.append("mp4a.40.2")
            continue
        if name == "opus":
            values.append("opus")
            continue
        if name == "mp3":
            values.append("mp4a.40.34")
            continue
        raw = _extradata(stream)
        if name == "h264":
            values.append("avc1." + raw[1:4].hex())
        elif name == "av1":
            values.append("av01.%d.%02d%s.%02d" % (
                raw[1] >> 5,
                raw[1] & 31,
                "H" if raw[2] & 128 else "M",
                12 if raw[2] & 32 else 10 if raw[2] & 64 else 8,
            ))
        elif name == "hevc":
            compatibility = int(f"{int.from_bytes(raw[2:6], 'big'):032b}"[::-1], 2)
            constraints = raw[6:12].rstrip(b"\0")
            tag = stream.get("codec_tag_string", "hvc1")
            if tag not in ("hvc1", "hev1"):
                tag = "hvc1"
            values.append((tag + ".%s%d.%X.%s%d%s") % (
                " ABC"[raw[1] >> 6].strip(),
                raw[1] & 31,
                compatibility,
                "H" if raw[1] & 32 else "L",
                raw[12],
                "".join(".%X" % byte for byte in constraints),
            ))
        else:
            raise CodecProbeError(f"unsupported codec for HLS metadata: {name}")
    if not values:
        raise CodecProbeError(f"no codec streams found in {init_segment}")
    return ",".join(values)


def _extradata(stream: dict) -> bytes:
    text = stream.get("extradata") or ""
    chunks: list[str] = []
    for line in text.strip().splitlines():
        payload = line.split(":", 1)[1] if ":" in line else line
        payload = payload.split("  ")[0].replace(" ", "")
        if payload:
            chunks.append(payload)
    try:
        return bytes.fromhex("".join(chunks))
    except ValueError as error:
        raise CodecProbeError(f"invalid extradata for {stream.get('codec_name')}: {error}") from error


def probe_dimensions(init_segment: str | Path, ffprobe: str | None = None) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    executable = _resolve_ffprobe(ffprobe)
    command = [
        executable, "-v", "fatal", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json",
        str(init_segment),
    ]
    try:
        data = json.loads(subprocess.check_output(command, stderr=subprocess.STDOUT))
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as error:
        raise CodecProbeError(f"unable to probe dimensions of {init_segment}: {error}") from error
    streams = data.get("streams") or []
    if not streams:
        raise CodecProbeError(f"no video stream found in {init_segment}")
    return int(streams[0]["width"]), int(streams[0]["height"])
