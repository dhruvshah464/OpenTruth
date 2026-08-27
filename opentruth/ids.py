"""ID namespaces for the evidence graph."""

from __future__ import annotations

import re

PREFIXES = ("R-", "C-", "A-", "O-", "E-", "S-")

_PATTERN = re.compile(r"^(R|C|A|O|E|S)-(\d+)$")


def parse_id(value: str) -> tuple[str, int]:
    match = _PATTERN.match(value)
    if not match:
        raise ValueError(f"invalid evidence id: {value!r}")
    return match.group(1) + "-", int(match.group(2))


def format_id(prefix: str, n: int) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown prefix: {prefix}")
    if prefix in ("A-", "O-", "E-", "S-"):
        return f"{prefix}{n:03d}"
    return f"{prefix}{n}"
