"""OpenTruth product server: the engine, served. Not a marketplace."""

from __future__ import annotations

import io
import os
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from opentruth import __version__
from opentruth.diff import diff_runs
from opentruth.engine import verify
from opentruth.explain import explain_text
from opentruth.graph import load_graph
from opentruth.store import IntegrityError, load_json, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
SITE = Path(__file__).resolve().parent / "site"
FIXTURE = ROOT / "examples" / "miniauth"
RUNS_ROOT = ROOT / ".opentruth" / "web-runs"
RUN_ID_RE = re.compile(r"^[a-f0-9]{8}$")
NODE_ID_RE = re.compile(r"^[RCAOE]-[0-9]+$", re.I)
FILE_KINDS = {"screenshots", "network", "artifacts"}
_VERIFY_LOCK = threading.Semaphore(2)
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opentruth")

Mode = Literal["browser", "api", "state"]
LoopMode = Literal["api", "state"]


class VerifyRequest(BaseModel):
    mode: Mode = "api"
    persist_session: bool = False
    write_identity: bool = False
    llm: bool = False


class DiffRequest(BaseModel):
    left: str = Field(min_length=8, max_length=8)
    right: str = Field(min_length=8, max_length=8)


class LoopRequest(BaseModel):
    mode: LoopMode = "api"


class Busy(RuntimeError):
    pass


def _runs_root() -> Path:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    return RUNS_ROOT


def _run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(404, "unknown run")
    path = _runs_root() / run_id
    if not (path / "manifest.json").is_file():
        raise HTTPException(404, "unknown run")
    return path


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 400:
            return value[:400] + "…"
        return value
    return None


def _node_public(nid: str, node: dict[str, Any], result: Any) -> dict[str, Any]:
    return {
        "id": nid,
        "kind": node.get("kind"),
        "payload_kind": node.get("payload_kind"),
        "statement": node.get("statement"),
        "check": node.get("check"),
        "result": result,
        "detail": _scalar(node.get("detail")),
        "type": node.get("type"),
        "target": node.get("target"),
        "side": node.get("side"),
        "run_id": node.get("run_id"),
        "value": _scalar(node.get("value")),
        "status": node.get("status"),
        "method": node.get("method"),
        "url": _scalar(node.get("url")),
        "path": node.get("path"),
        "expect": _scalar(node.get("expect")),
        "cites": node.get("cites") if isinstance(node.get("cites"), list) else None,
        "artifact": node.get("artifact"),
        "network_path": node.get("network_path"),
        "error": _scalar(node.get("error")),
    }


def _verdict_payload(verdict: dict[str, Any], run_id: str, run_dir: Path) -> dict[str, Any]:
    req = (verdict.get("requirements") or [{}])[0]
    created = None
    try:
        created = load_json(run_dir / "manifest.json").get("created_at")
    except Exception:
        pass
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "verdict": req.get("verdict"),
        "confidence": req.get("confidence"),
        "statement": req.get("statement"),
        "constraints": req.get("constraints") or [],
        "summary": verdict.get("summary") or {},
        "left": verdict.get("left"),
        "right": verdict.get("right"),
        "mode": verdict.get("mode"),
        "created_at": created,
    }


def _llm_configured() -> bool:
    env = os.environ
    return bool((env.get("OPENTRUTH_LLM_API_KEY") or env.get("OPENAI_API_KEY") or "").strip())


def _timeout_for(mode: str, loop: bool = False, llm: bool = False) -> float:
    extra = 60.0 if llm else 0.0
    if loop:
        return 120.0 + extra
    if mode == "browser":
        return 180.0 + extra
    return 90.0 + extra


def _call(fn, timeout: float):
    future = _POOL.submit(fn)
    try:
        return future.result(timeout=timeout)
    except Busy:
        raise HTTPException(429, "engine busy; retry shortly") from None
    except FuturesTimeout:
        raise HTTPException(504, "engine timed out") from None


def _locked_verify(**kwargs: Any) -> dict[str, Any]:
    if not _VERIFY_LOCK.acquire(blocking=False):
        raise Busy("engine busy")
    try:
        return verify(FIXTURE, runs_root=_runs_root(), **kwargs)
    finally:
        _VERIFY_LOCK.release()


def _locked_diff(left: Path, right: Path) -> dict[str, Any]:
    if not _VERIFY_LOCK.acquire(blocking=False):
        raise Busy("engine busy")
    try:
        return diff_runs(left, right, _runs_root())
    finally:
        _VERIFY_LOCK.release()


def _locked_loop(mode: str) -> dict[str, Any]:
    if not _VERIFY_LOCK.acquire(blocking=False):
        raise Busy("engine busy")
    try:
        planted_kw: dict[str, Any] = {"mode": mode, "persist_session": False, "write_identity": False}
        if mode == "state":
            fixed_kw: dict[str, Any] = {"mode": mode, "persist_session": False, "write_identity": True}
        else:
            fixed_kw = {"mode": mode, "persist_session": True, "write_identity": False}
        planted = verify(FIXTURE, runs_root=_runs_root(), **planted_kw)
        fixed = verify(FIXTURE, runs_root=_runs_root(), **fixed_kw)
        delta = diff_runs(planted["run_dir"], fixed["run_dir"], _runs_root())
        return {"planted": planted, "fixed": fixed, "diff": delta}
    finally:
        _VERIFY_LOCK.release()


def _list_blob_urls(run_id: str, kind: str, run_dir: Path) -> list[dict[str, str]]:
    folder = run_dir / kind
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.iterdir()):
        if path.is_file():
            items.append(
                {
                    "name": path.name,
                    "kind": kind,
                    "url": f"/api/v1/runs/{run_id}/file/{kind}/{path.name}",
                }
            )
    return items


def _latest_summary() -> dict[str, Any] | None:
    root = _runs_root()
    if not root.is_dir():
        return None
    sealed = [p for p in root.iterdir() if p.is_dir() and (p / "verdict.json").is_file()]
    if not sealed:
        return None
    path = max(sealed, key=lambda p: p.stat().st_mtime)
    try:
        verdict = load_json(path / "verdict.json")
    except Exception:
        return None
    req = (verdict.get("requirements") or [{}])[0]
    return {
        "run_id": path.name,
        "verdict": req.get("verdict"),
        "confidence": req.get("confidence"),
        "mode": verdict.get("mode"),
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenTruth",
        description="Independent verification that software satisfies a requirement.",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8787", "http://localhost:8787"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        path = request.url.path
        if path.startswith("/css/") or path.startswith("/js/") or path == "/favicon.svg":
            response.headers["Cache-Control"] = "public, max-age=120"
        elif path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            page = SITE / "404.html"
            if page.is_file():
                return FileResponse(page, status_code=404, media_type="text/html; charset=utf-8")
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        root = _runs_root()
        count = 0
        if root.is_dir():
            count = sum(1 for p in root.iterdir() if p.is_dir() and (p / "manifest.json").is_file())
        return {
            "ok": True,
            "engine": "opentruth",
            "version": __version__,
            "fixture": FIXTURE.is_dir(),
            "runs": count,
            "latest": _latest_summary(),
            "llm": _llm_configured(),
        }

    @app.get("/api/v1/product")
    def product() -> dict[str, Any]:
        return {
            "name": "OpenTruth",
            "principle": "Verifier ≠ Builder",
            "verdicts": ["PROVEN", "PARTIALLY_PROVEN", "FAILED", "NOT_PROVEN", "INCONCLUSIVE"],
            "layers": [
                {"id": "M1", "name": "Browser proof"},
                {"id": "M2", "name": "API proof"},
                {"id": "M3", "name": "State / invariant proof"},
                {"id": "M4", "name": "Change / diff proof"},
                {"id": "M5", "name": "Continuous verification"},
                {"id": "M6", "name": "AI-assisted planning"},
            ],
            "console": {
                "subject": "MiniAuth",
                "planted": "Session does not persist; identity row skipped in state mode",
                "loop": "planted → claimed fix → diff",
            },
            "identity": ["protocol", "product", "adapter"],
            "experiments": [
                {"name": "MiniAuth", "planner": "deterministic", "role": "v0.1 freeze"},
                {"name": "MiniTodos", "planner": "ir", "role": "v0.3 IR generalization"},
            ],
        }

    @app.get("/api/v1/runs")
    def list_runs() -> dict[str, Any]:
        root = _runs_root()
        items = []
        listing = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if root.is_dir() else []
        for path in listing:
            if not path.is_dir() or not (path / "verdict.json").is_file():
                continue
            try:
                verdict = load_json(path / "verdict.json")
            except Exception:
                continue
            req = (verdict.get("requirements") or [{}])[0]
            plan: dict[str, Any] = {}
            created = None
            try:
                plan = load_json(path / "plan.json")
            except Exception:
                pass
            try:
                created = load_json(path / "manifest.json").get("created_at")
            except Exception:
                pass
            items.append(
                {
                    "run_id": path.name,
                    "verdict": req.get("verdict"),
                    "confidence": req.get("confidence"),
                    "mode": plan.get("mode") or verdict.get("mode"),
                    "planner": plan.get("planner"),
                    "created_at": created,
                    "left": (verdict.get("left") or {}).get("run_id"),
                    "right": (verdict.get("right") or {}).get("run_id"),
                }
            )
            if len(items) >= 24:
                break
        return {"runs": items}

    @app.post("/api/v1/verify")
    def api_verify(body: VerifyRequest) -> dict[str, Any]:
        if not FIXTURE.is_dir():
            raise HTTPException(500, "MiniAuth fixture missing")
        try:
            result = _call(
                lambda: _locked_verify(
                    persist_session=body.persist_session,
                    write_identity=body.write_identity,
                    mode=body.mode,
                    llm=True if body.llm else None,
                ),
                timeout=_timeout_for(body.mode, llm=body.llm),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"verify failed: {exc}") from exc
        return _verdict_payload(result["verdict"], result["run_id"], result["run_dir"])

    @app.post("/api/v1/loop")
    def api_loop(body: LoopRequest) -> dict[str, Any]:
        """Planted proof, claimed-fix proof, then sealed diff. The working product loop."""
        if not FIXTURE.is_dir():
            raise HTTPException(500, "MiniAuth fixture missing")
        try:
            result = _call(lambda: _locked_loop(body.mode), timeout=_timeout_for(body.mode, loop=True))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"loop failed: {exc}") from exc
        out = {}
        for key in ("planted", "fixed", "diff"):
            item = result[key]
            out[key] = _verdict_payload(item["verdict"], item["run_id"], item["run_dir"])
        return out

    @app.post("/api/v1/diff")
    def api_diff(body: DiffRequest) -> dict[str, Any]:
        left = _run_dir(body.left)
        right = _run_dir(body.right)
        if body.left == body.right:
            raise HTTPException(400, "diff requires two distinct runs")
        try:
            result = _call(lambda: _locked_diff(left, right), timeout=60.0)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"diff failed: {exc}") from exc
        return _verdict_payload(result["verdict"], result["run_id"], result["run_dir"])

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        path = _run_dir(run_id)
        graph = load_graph(path)
        req = (graph.verdict.get("requirements") or [{}])[0]
        nodes = []
        for nid, node in graph.nodes.items():
            result = node.get("result") or graph.constraint_result(nid)
            if node.get("kind") == "requirement":
                block = graph.requirement_verdict(nid)
                if block:
                    result = block.get("verdict")
            nodes.append(_node_public(nid, node, result))
        return {
            **_verdict_payload(graph.verdict, run_id, path),
            "integrity_ok": graph.integrity_ok,
            "integrity_error": graph.integrity_error,
            "plan": {
                "mode": (graph.plan or {}).get("mode"),
                "planner": (graph.plan or {}).get("planner"),
                "planner_model": (graph.plan or {}).get("planner_model"),
                "planner_requested": (graph.plan or {}).get("planner_requested"),
                "llm_error": (graph.plan or {}).get("llm_error"),
                "runner": (graph.plan or {}).get("runner"),
            },
            "nodes": nodes,
            "children": {k: v for k, v in graph.children.items()},
            "root": req.get("id") or "R-1",
            "files": {
                "screenshots": _list_blob_urls(run_id, "screenshots", path),
                "network": _list_blob_urls(run_id, "network", path),
                "artifacts": _list_blob_urls(run_id, "artifacts", path),
            },
        }

    @app.get("/api/v1/runs/{run_id}/explain/{node_id}")
    def explain_node(run_id: str, node_id: str) -> dict[str, Any]:
        if not NODE_ID_RE.match(node_id):
            raise HTTPException(400, "invalid node id")
        text, code = explain_text(_run_dir(run_id), node_id)
        return {"id": node_id, "code": code, "text": text}

    @app.get("/api/v1/runs/{run_id}/pack")
    def pack_run_download(run_id: str) -> Response:
        path = _run_dir(run_id)
        try:
            verify_manifest(path)
        except IntegrityError as exc:
            raise HTTPException(409, f"INTEGRITY FAILED: {exc}") from exc
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(path.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, Path(run_id) / file_path.relative_to(path))
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
        )

    @app.get("/api/v1/runs/{run_id}/file/{kind}/{name}")
    def run_file(run_id: str, kind: str, name: str) -> FileResponse:
        if kind not in FILE_KINDS or "/" in name or "\\" in name or name in {".", ".."}:
            raise HTTPException(404, "unknown file")
        path = (_run_dir(run_id) / kind / name).resolve()
        root = (_run_dir(run_id) / kind).resolve()
        if root not in path.parents and path != root:
            raise HTTPException(404, "unknown file")
        if not path.is_file():
            raise HTTPException(404, "unknown file")
        return FileResponse(path)

    def page(name: str):
        def _inner():
            path = SITE / name
            if not path.is_file():
                raise HTTPException(404)
            return FileResponse(path, media_type="text/html; charset=utf-8")

        return _inner

    app.add_api_route("/", page("index.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/engine", page("engine.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/evidence", page("evidence.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/console", page("console.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/docs", page("docs.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/company", page("company.html"), methods=["GET"], include_in_schema=False)

    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        path = SITE / "favicon.svg"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/svg+xml")

    if (SITE / "css").is_dir():
        app.mount("/css", StaticFiles(directory=SITE / "css"), name="css")
    if (SITE / "js").is_dir():
        app.mount("/js", StaticFiles(directory=SITE / "js"), name="js")
    if (SITE / "img").is_dir():
        app.mount("/img", StaticFiles(directory=SITE / "img"), name="img")

    return app


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    import uvicorn

    uvicorn.run("opentruth.server:app", host=host, port=port, reload=False)
