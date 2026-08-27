"""Sealed, append-only run directory. This is the product."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from opentruth import __version__
from opentruth.ids import format_id

JSONL_FILES = ("actions.jsonl", "observations.jsonl", "assertions.jsonl")
BLOB_DIRS = ("screenshots", "network", "artifacts")
FROZEN_JSON = ("requirements.json", "plan.json", "verdict.json")
MANIFEST_NAME = "manifest.json"


class StoreError(RuntimeError):
    pass


class IntegrityError(StoreError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def new_run_id() -> str:
    return uuid.uuid4().hex[:8]


class RunStore:
    """Write-once evidence store. After seal(), every file is hashed and made read-only."""

    def __init__(self, root: Path, run_id: str | None = None):
        self.run_id = run_id or new_run_id()
        self.root = Path(root) / self.run_id
        self.sealed = False
        self.created_at = _now()
        self._counters: dict[str, int] = {"A-": 0, "O-": 0, "E-": 0, "S-": 0}

    def create(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=False)
        for name in BLOB_DIRS:
            (self.root / name).mkdir()
        for name in JSONL_FILES:
            (self.root / name).write_text("", encoding="utf-8")
        return self.root

    def allocate(self, prefix: str) -> str:
        self._reject_if_sealed()
        self._counters[prefix] += 1
        return format_id(prefix, self._counters[prefix])

    def write_json(self, name: str, obj: Any) -> Path:
        self._reject_if_sealed()
        if name not in FROZEN_JSON:
            raise StoreError(f"json file not in schema: {name}")
        path = self.root / name
        if path.exists() and path.stat().st_size:
            raise StoreError(f"{name} already written")
        path.write_text(dumps(obj) + "\n", encoding="utf-8")
        return path

    def append(self, filename: str, record: dict[str, Any]) -> dict[str, Any]:
        self._reject_if_sealed()
        if filename not in JSONL_FILES:
            raise StoreError(f"not a jsonl file: {filename}")
        if "timestamp" not in record:
            record = {**record, "timestamp": _now()}
        line = dumps(record)
        with (self.root / filename).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return record

    def write_blob(self, subdir: str, filename: str, data: bytes) -> str:
        self._reject_if_sealed()
        if subdir not in BLOB_DIRS:
            raise StoreError(f"unknown blob dir: {subdir}")
        rel = f"{subdir}/{filename}"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise StoreError(f"blob already exists: {rel}")
        path.write_bytes(data)
        return rel.replace("\\", "/")

    def seal(self) -> dict[str, Any]:
        self._reject_if_sealed()
        for required in ("requirements.json", "plan.json", "verdict.json"):
            if not (self.root / required).is_file():
                raise StoreError(f"cannot seal without {required}")
        files: dict[str, dict[str, str]] = {}
        for path in _iter_files(self.root):
            rel = path.relative_to(self.root).as_posix()
            if rel == MANIFEST_NAME:
                continue
            files[rel] = {"sha256": _sha256_file(path)}
        manifest = {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "sealed_at": _now(),
            "opentruth_version": __version__,
            "sealed": True,
            "files": files,
        }
        (self.root / MANIFEST_NAME).write_text(dumps(manifest) + "\n", encoding="utf-8")
        self.sealed = True
        _freeze_tree(self.root)
        return manifest

    def _reject_if_sealed(self) -> None:
        if self.sealed:
            raise StoreError("run is sealed; records are immutable")


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _freeze_tree(root: Path) -> None:
    for path in _iter_files(root):
        mode = path.stat().st_mode
        path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def verify_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise IntegrityError(f"missing {MANIFEST_NAME}")
    manifest = load_json(manifest_path)
    if not manifest.get("sealed"):
        raise IntegrityError("run is not sealed")
    files = manifest.get("files") or {}
    expected = {rel: meta["sha256"] for rel, meta in files.items()}
    actual: dict[str, str] = {}
    for path in _iter_files(run_dir):
        rel = path.relative_to(run_dir).as_posix()
        if rel == MANIFEST_NAME:
            continue
        actual[rel] = _sha256_file(path)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(
        rel for rel in expected.keys() & actual.keys() if expected[rel] != actual[rel]
    )
    if missing or extra or mismatched:
        details = []
        if missing:
            details.append(f"missing: {missing}")
        if extra:
            details.append(f"extra: {extra}")
        if mismatched:
            details.append(
                "changed: "
                + ", ".join(f"{rel} expected {expected[rel]} got {actual[rel]}" for rel in mismatched)
            )
        raise IntegrityError("; ".join(details))
    return manifest


def latest_run(runs_root: Path) -> Path | None:
    if not runs_root.is_dir():
        return None
    sealed = [p for p in runs_root.iterdir() if p.is_dir() and (p / MANIFEST_NAME).is_file()]
    if not sealed:
        return None
    return max(sealed, key=lambda p: p.stat().st_mtime)
