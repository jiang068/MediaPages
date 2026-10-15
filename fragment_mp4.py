"""Split a fragmented MP4 into HLS segments without changing any bytes.

FFmpeg's fMP4 HLS muxer cannot always honour both ``hls_time`` and a maximum
segment size: a single keyframe interval of high-bitrate 4K HEVC can exceed a
25 MiB deployment limit. This module asks FFmpeg for one fragmented MP4 with a
fixed ``-frag_size``, then re-partitions the file at ``moof``/``mdat``
boundaries. The video and audio payload bytes are copied verbatim; only the
container's segment boundaries move, and a new playlist is written.

Ported from the EVA site build so any MediaPages library can use the same trick.
"""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
from pathlib import Path


class FragmentError(RuntimeError):
    pass


def repartition(
    source: str | Path,
    folder: str | Path,
    fragment_bytes: int = 18 * 1024 * 1024,
    *,
    ffmpeg: str = "ffmpeg",
    tag_hvc1: bool = True,
    audio_codec: str = 'copy',
    audio_bitrate: str | None = None,
    init_name: str = "init.mp4",
    segment_pattern: str = "segment_%05d.m4s",
    playlist_name: str = "playlist.m3u8",
) -> list[tuple[str, float]]:
    """Return a list of ``(segment_name, seconds)`` written into ``folder``.

    ``source`` is the original Matroska/MP4 file. A temporary fragmented MP4 is
    created next to the output, split at ``moof``/``mdat`` boundaries, and
    removed afterwards.
    """
    source = Path(source)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    intermediate = folder / (source.stem + ".fragmented.mp4")

    command = [
        ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", audio_codec,
        "-map_metadata", "-1", "-map_chapters", "-1",
    ]
    if audio_codec != 'copy' and audio_bitrate:
        command += ['-b:a', audio_bitrate]
    if tag_hvc1:
        command += ["-tag:v", "hvc1"]
    command += [
        "-movflags", "empty_moov+default_base_moof+frag_keyframe+dash",
        "-frag_size", str(int(fragment_bytes)),
        "-f", "mp4", str(intermediate),
    ]
    subprocess.run(command, check=True, stderr=subprocess.DEVNULL)

    for old in folder.glob("segment_*.m4s"):
        old.unlink()
    for old in folder.glob(init_name):
        old.unlink()

    prefix: list[bytes] = []
    duration: float | None = None
    alternate: float | None = None
    segments: list[tuple[str, float]] = []
    last: Path | None = None
    has_moof = False

    with intermediate.open("rb") as handle, (folder / init_name).open("wb") as init:
        while True:
            header = handle.read(8)
            if not header:
                break
            if len(header) != 8:
                raise FragmentError("truncated box header")
            length, kind = struct.unpack(">I4s", header)
            if length == 1:
                extra = handle.read(8)
                header += extra
                length = struct.unpack(">Q", extra)[0]
            if length < len(header):
                raise FragmentError(f"invalid box length for {kind!r}")
            remaining = length - len(header)
            if kind == b"mdat":
                if not has_moof or not prefix:
                    raise FragmentError("mdat without preceding moof")
                name = _segment_name(segment_pattern, len(segments))
                target = folder / name
                with target.open("wb") as output:
                    for block in prefix:
                        output.write(block)
                    output.write(header)
                    while remaining:
                        block = handle.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise FragmentError("unexpected end of mdat")
                        output.write(block)
                        remaining -= len(block)
                seconds = duration or alternate
                if not seconds or seconds <= 0:
                    raise FragmentError("segment has no duration")
                segments.append((name, seconds))
                last = target
                prefix = []
                duration = None
                alternate = None
                has_moof = False
            else:
                body = handle.read(remaining)
                if len(body) != remaining:
                    raise FragmentError("unexpected end of box")
                block = header + body
                if kind in (b"ftyp", b"moov") or (not segments and not prefix and kind == b"free"):
                    init.write(block)
                elif kind == b"mfra":
                    if last is None:
                        raise FragmentError("mfra before any segment")
                    with last.open("ab") as output:
                        output.write(block)
                else:
                    prefix.append(block)
                    if kind == b"moof":
                        has_moof = True
                    if kind == b"sidx":
                        version = body[0]
                        reference_id, timescale = struct.unpack_from(">II", body, 4)
                        offset = 12 + (16 if version else 8)
                        count = struct.unpack_from(">H", body, offset + 2)[0]
                        total = sum(
                            struct.unpack_from(">I", body, offset + 4 + i * 12 + 4)[0]
                            for i in range(count)
                        )
                        seconds = total / timescale if timescale else 0
                        if reference_id == 1:
                            duration = seconds
                        else:
                            alternate = seconds
        if prefix:
            raise FragmentError("trailing boxes without mdat")

    write_playlist(folder, segments, init_name, playlist_name)
    intermediate.unlink(missing_ok=True)
    return segments


def _segment_name(pattern: str, index: int) -> str:
    """支持 ``segment_%05d.m4s`` 与 ``segment_{index:05d}.m4s`` 两种模板。"""
    if "%" in pattern:
        return pattern % index
    return pattern.format(index=index)


def write_playlist(folder: Path, segments: list[tuple[str, float]], init_name: str,
                   playlist_name: str = "playlist.m3u8") -> Path:
    if not segments:
        raise FragmentError("no segments were produced")
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{math.ceil(max(seconds for _, seconds in segments))}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        f'#EXT-X-MAP:URI="{init_name}"',
    ]
    for name, seconds in segments:
        lines += [f"#EXTINF:{seconds:.6f},", name]
    lines.append("#EXT-X-ENDLIST")
    playlist = folder / playlist_name
    playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return playlist


def probe_video_codec(source: str | Path, ffprobe: str = "ffprobe") -> str:
    import json
    output = subprocess.check_output([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "json", str(source),
    ])
    streams = json.loads(output).get("streams") or []
    if not streams:
        raise FragmentError(f"no video stream in {source}")
    return streams[0]["codec_name"]
