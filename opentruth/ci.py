"""CI surface: machine-readable outputs and a portable sealed-run bundle.

Not a service. The job fails or passes from the CLI exit code; the artifact is
the same sealed directory `opentruth explain` already walks.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Mapping

from opentruth.store import IntegrityError, verify_manifest


def format_github_summary(verdict: dict, run_dir: Path) -> str:
    req = (verdict.get("requirements") or [{}])[0]
    s = verdict.get("summary") or {}
    pct = int(round(float(s.get("confidence") or 0) * 100))
    lines = [
        "## OpenTruth",
        "",
        f"**{req.get('verdict', 'UNKNOWN')}**  confidence {pct}%",
        "",
    ]
    left = verdict.get("left") or {}
    right = verdict.get("right") or {}
    if left.get("run_id") and right.get("run_id"):
        lines.append(f"Compared `{left['run_id']}` → `{right['run_id']}`")
        lines.append("")
    if "improved" in s:
        lines.append(
            f"Improved {s.get('improved', 0)} · "
            f"Regressed {s.get('regressed', 0)} · "
            f"Unchanged {s.get('unchanged', 0)}"
        )
        lines.append("")
    lines.extend(["| Constraint | Result |", "|---|---|"])
    for row in req.get("constraints") or []:
        lines.append(f"| `{row.get('id', '')}` | {row.get('result', '')} |")
    lines.extend(
        [
            "",
            f"Evidence `{run_dir}`",
            "",
            f"Walk: `opentruth explain R-1 --run {run_dir}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_ci_outputs(verdict: dict, run_dir: Path, dest: Path) -> None:
    req = (verdict.get("requirements") or [{}])[0]
    s = verdict.get("summary") or {}
    conf = s.get("confidence")
    rows = [
        f"verdict={req.get('verdict', '')}",
        f"run-id={verdict.get('run_id') or run_dir.name}",
        f"run-dir={Path(run_dir).resolve()}",
        f"confidence={conf if conf is not None else ''}",
    ]
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    prefix = existing if existing.endswith("\n") or not existing else existing + "\n"
    dest.write_text(prefix + "\n".join(rows) + "\n", encoding="utf-8")


def emit_ci(verdict: dict, run_dir: Path, env: Mapping[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    out = env.get("OPENTRUTH_OUTPUT") or env.get("GITHUB_OUTPUT")
    if out:
        write_ci_outputs(verdict, run_dir, Path(out))
    summary = env.get("OPENTRUTH_SUMMARY") or env.get("GITHUB_STEP_SUMMARY")
    if summary:
        path = Path(summary)
        body = format_github_summary(verdict, run_dir)
        if path.is_file():
            path.write_text(path.read_text(encoding="utf-8") + body, encoding="utf-8")
        else:
            path.write_text(body, encoding="utf-8")


def pack_run(run_dir: Path, dest: Path) -> Path:
    """Zip a sealed run. Refuses tampered evidence."""
    run_dir = Path(run_dir).resolve()
    verify_manifest(run_dir)
    dest = Path(dest)
    if dest.suffix.lower() != ".zip":
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / f"{run_dir.name}.zip"
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file():
                continue
            arcname = Path(run_dir.name) / path.relative_to(run_dir)
            archive.write(path, arcname.as_posix())
    return dest.resolve()


def pack_error_exit(exc: Exception) -> int:
    if isinstance(exc, IntegrityError):
        return 3
    if isinstance(exc, FileNotFoundError):
        return 2
    return 1
