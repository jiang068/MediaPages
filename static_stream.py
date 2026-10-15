"""Publish a large file as byte-exact static chunks behind one Range URL.

Cloudflare Pages caps each static asset (25 MiB by default) and the Free plan
caps the number of files. For containers that browsers may still open natively
(notably MKV with embedded ASS and chapters), the most faithful publishing
strategy is to keep the original bytes: split the file into fixed-size parts,
store a manifest, and serve the canonical URL through a Pages Function that
stitches ``Range`` requests back together.

No transcoding happens here, so audio, subtitles, chapters and attachments all
survive untouched.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chunk:
    path: str
    bytes: int
    sha256: str


@dataclass
class StreamEntry:
    id: str
    name: str
    size: int
    sha256: str
    mime: str
    chunks: list[Chunk] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    relative_path: str | None = None
    subtitles: list[dict] = field(default_factory=list)
    ass_tracks: list[dict] = field(default_factory=list)

    def to_manifest(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
            "mime": self.mime,
            "relative_path": self.relative_path,
            "subtitles": self.subtitles,
            "ass": self.ass_tracks,
            "chunks": [{"path": c.path, "bytes": c.bytes, "sha256": c.sha256} for c in self.chunks],
        }


def split_file(
    source: str | Path,
    dist: str | Path,
    stream_id: str,
    *,
    part_bytes: int = 24 * 1024 * 1024,
    mime: str = "application/octet-stream",
    url_prefix: str = "/stream/chunks",
) -> StreamEntry:
    """Split ``source`` into ``part_XXXXX.bin`` under ``dist`` and return metadata.

    Chunks are versioned by the source SHA-256 prefix so a rebuilt library never
    serves stale bytes for an existing URL.
    """
    if part_bytes <= 0:
        raise ValueError("part_bytes must be positive")
    source = Path(source)
    dist = Path(dist)
    if not source.is_file():
        raise FileNotFoundError(source)

    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    sha256 = digest.hexdigest()
    identity = sha256[:16]

    folder = dist / stream_id / identity
    folder.mkdir(parents=True, exist_ok=True)

    chunks: list[Chunk] = []
    count = max(1, math.ceil(size / part_bytes))
    copied_digest = hashlib.sha256()
    with source.open("rb") as handle:
        for index in range(count):
            data = handle.read(part_bytes)
            if not data:
                break
            name = f"part_{index:05d}.bin"
            target = folder / name
            copied_digest.update(data)
            part_hash = hashlib.sha256(data).hexdigest()
            if not target.is_file() or target.stat().st_size != len(data) or hashlib.sha256(target.read_bytes()).hexdigest() != part_hash:
                temporary = target.with_suffix('.bin.next')
                temporary.write_bytes(data)
                temporary.replace(target)
            chunks.append(Chunk(
                path=f"{url_prefix.rstrip('/')}/{stream_id}/{identity}/{name}",
                bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            ))
    if copied_digest.hexdigest() != sha256 or sum(chunk.bytes for chunk in chunks) != size:
        raise RuntimeError(f"chunk total does not match source size for {source}")

    return StreamEntry(id=stream_id, name=source.name, size=size, sha256=sha256,
                       mime=mime, chunks=chunks)


def write_manifest(dist: str | Path, entries: list[StreamEntry], name: str = "manifest.json") -> Path:
    """Write the manifest consumed by the Pages Function."""
    dist = Path(dist)
    dist.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "files": {entry.id: entry.to_manifest() for entry in entries},
    }
    path = dist / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
