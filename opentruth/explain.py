"""Evidence graph explorer in CLI form."""

from __future__ import annotations

from pathlib import Path

from opentruth.graph import EvidenceGraph, load_graph
from opentruth.store import latest_run

_BOX = "─" * 29


def _result_badge(node: dict, graph: EvidenceGraph) -> str:
    kind = node.get("kind")
    if kind == "requirement":
        block = graph.requirement_verdict(node["id"])
        return (block or {}).get("verdict", "")
    if kind == "constraint":
        return (graph.constraint_result(node["id"]) or "").upper()
    if kind == "assertion":
        return str(node.get("result", "")).upper()
    return ""


def _line(node_id: str, graph: EvidenceGraph) -> str:
    node = graph.get(node_id)
    kind = node["kind"]
    badge = _result_badge(node, graph)
    suffix = f"  {badge}" if badge else ""
    if kind == "requirement":
        return f"{node_id}  {node.get('statement', '')}{suffix}"
    if kind == "constraint":
        return f"{node_id}  {node.get('statement', '')}{suffix}"
    if kind == "action":
        err = f"  error={node['error']}" if node.get("error") else ""
        net = f"  network={node.get('network_path')}" if node.get("network_path") else ""
        return f"{node_id}  {node.get('type')} {node.get('target', '')}{err}{net}"
    if kind == "observation":
        okind = node.get("payload_kind") or "observation"
        if okind == "diff":
            side = node.get("side") or ""
            run_id = node.get("run_id") or ""
            value = node.get("value")
            return f"{node_id}  diff {side} run={run_id} {value}".rstrip()
        path = node.get("path") or ""
        value = node.get("value")
        extra = path or (repr(value)[:80] if value else "")
        return f"{node_id}  {okind} {extra}".rstrip()
    if kind == "assertion":
        cites = ",".join(node.get("cites") or []) or "-"
        art = f"  artifact={node['artifact']}" if node.get("artifact") else ""
        return (
            f"{node_id}  {node.get('check')} expect={node.get('expect')!r} "
            f"cites {cites}  {node.get('detail', '')}{art}{suffix}"
        )
    return f"{node_id}  {kind}"


def render_tree(graph: EvidenceGraph, root_id: str) -> str:
    lines: list[str] = []

    def walk(node_id: str, prefix: str, is_last: bool, is_root: bool) -> None:
        branch = "" if is_root else ("└── " if is_last else "├── ")
        lines.append(f"{prefix}{branch}{_line(node_id, graph)}")
        children = graph.children.get(node_id, [])
        child_prefix = prefix if is_root else prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            walk(child, child_prefix, i == len(children) - 1, False)

    walk(root_id, "", True, True)
    return "\n".join(lines)


def render_focus(graph: EvidenceGraph, node_id: str) -> str:
    node = graph.get(node_id)
    kind = node["kind"]
    chunks = [_line(node_id, graph), ""]
    if kind == "assertion":
        chunks.append(f"constraint  {node.get('constraint_id')}")
        chunks.append(f"cites       {', '.join(node.get('cites') or []) or '-'}")
        for oid in node.get("cites") or []:
            if oid in graph.nodes:
                chunks.append("  " + _line(oid, graph))
                obs = graph.get(oid)
                if obs.get("action_id"):
                    chunks.append("  produced by " + _line(obs["action_id"], graph))
        parent = node.get("constraint_id")
        if parent:
            req = graph.nodes.get(parent, {}).get("requirement_id")
            if req:
                block = graph.requirement_verdict(req)
                chunks.append("")
                chunks.append(
                    f"drove {req} verdict {(block or {}).get('verdict')}"
                )
        if node.get("artifact"):
            chunks.append(f"artifact    {node['artifact']}")
        return "\n".join(chunks)
    return render_tree(graph, node_id)


def format_verify_summary(verdict: dict, run_dir: Path) -> str:
    s = verdict["summary"]
    pct = int(round(float(s.get("confidence") or 0) * 100))
    lines = [
        "OPEN TRUTH",
        _BOX,
        "",
        f"Requirements        {s['requirements']}",
        f"Verified            {s['proven']}",
        f"Partially verified  {s['partially_proven']}",
        f"Failed              {s['failed']}",
        f"Inconclusive        {s['inconclusive']}",
        "",
        f"Confidence          {pct}%",
        "",
        f"Critical failures   {s['critical_failures']}",
    ]
    left = verdict.get("left") or {}
    right = verdict.get("right") or {}
    if left.get("run_id") and right.get("run_id"):
        lines.extend(["", f"Compared            {left['run_id']} → {right['run_id']}"])
    if "improved" in s:
        lines.extend(
            [
                "",
                f"Improved            {s.get('improved', 0)}",
                f"Regressed           {s.get('regressed', 0)}",
                f"Unchanged           {s.get('unchanged', 0)}",
            ]
        )
    lines.extend(["", f"Evidence            {run_dir}"])
    return "\n".join(lines)


def explain_text(run_dir: Path, node_id: str) -> tuple[str, int]:
    graph = load_graph(run_dir)
    header = [f"run {graph.manifest.get('run_id', run_dir.name)}  {run_dir}"]
    plan = graph.plan or {}
    if plan.get("mode") == "diff":
        left = plan.get("left") or {}
        right = plan.get("right") or {}
        header.append(f"diff {left.get('run_id')} → {right.get('run_id')}")
    if not graph.integrity_ok:
        body = "\n".join(
            [
                *header,
                "",
                "INTEGRITY FAILED",
                f"  {graph.integrity_error}",
                "",
                "Stored verdict is not authoritative.",
            ]
        )
        return body, 3
    if node_id not in graph.nodes:
        return "\n".join([*header, "", f"unknown id {node_id}"]), 2
    prefix = node_id.split("-")[0]
    body = render_focus(graph, node_id) if prefix == "E" else render_tree(graph, node_id)
    return "\n".join([*header, "", body]), 0


def resolve_run(explicit: str | None, search_from: Path) -> Path:
    if explicit:
        path = Path(explicit)
        if path.is_dir():
            return path
        raise FileNotFoundError(path)
    root = search_from / ".opentruth" / "runs"
    latest = latest_run(root)
    if latest is None:
        raise FileNotFoundError(f"no sealed runs in {root}")
    return latest
