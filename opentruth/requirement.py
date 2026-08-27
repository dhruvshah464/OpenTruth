"""Load a human YAML requirement file and freeze R-*/C-* identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from opentruth.ids import format_id


@dataclass(frozen=True)
class Constraint:
    id: str
    requirement_id: str
    statement: str
    kind: str  # happy_path | constraint


@dataclass(frozen=True)
class Requirement:
    id: str
    statement: str
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)

    def happy_path(self) -> Constraint:
        for constraint in self.constraints:
            if constraint.kind == "happy_path":
                return constraint
        raise ValueError(f"{self.id} has no happy-path constraint")

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "constraints": [asdict(c) for c in self.constraints],
        }


@dataclass(frozen=True)
class RequirementDocument:
    """Requirement language plus optional Verification IR. Not the execution plan."""

    requirement: Requirement
    verification: Any = None
    path: Path | None = None


def load_requirement_document(path: Path, requirement_index: int = 1) -> RequirementDocument:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    statement = raw.get("requirement") or raw.get("statement")
    if not statement or not isinstance(statement, str):
        raise ValueError(f"{path} needs a 'requirement' string")
    req_id = raw.get("id") or format_id("R-", requirement_index)
    constraints: list[Constraint] = [
        Constraint(
            id=format_id("C-", 0),
            requirement_id=req_id,
            statement=statement.strip(),
            kind="happy_path",
        )
    ]
    listed = raw.get("constraints") or []
    if not isinstance(listed, list):
        raise ValueError("constraints must be a list")
    for i, item in enumerate(listed, start=1):
        if isinstance(item, str):
            text = item.strip()
            cid = format_id("C-", i)
        elif isinstance(item, dict):
            text = str(item.get("statement") or item.get("text") or "").strip()
            cid = str(item.get("id") or format_id("C-", i))
        else:
            raise ValueError(f"bad constraint: {item!r}")
        if not text:
            raise ValueError("constraint statement is empty")
        constraints.append(
            Constraint(
                id=cid,
                requirement_id=req_id,
                statement=text,
                kind="constraint",
            )
        )
    return RequirementDocument(
        requirement=Requirement(id=req_id, statement=statement.strip(), constraints=tuple(constraints)),
        verification=raw.get("verification"),
        path=path,
    )


def load_requirements(path: Path, requirement_index: int = 1) -> Requirement:
    return load_requirement_document(path, requirement_index).requirement
