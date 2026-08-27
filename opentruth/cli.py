"""opentruth verify / explain / diff / pack."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opentruth.ci import emit_ci, pack_error_exit, pack_run
from opentruth.diff import diff_runs, resolve_run_arg
from opentruth.engine import verify
from opentruth.explain import explain_text, format_verify_summary, resolve_run
from opentruth.store import IntegrityError
from opentruth.verdicts import exit_code


def cmd_verify(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    runs_root = Path(args.out).resolve() if args.out else None
    persist = None
    if args.persist_session:
        persist = True
    if args.no_persist_session:
        persist = False
    identity = None
    if args.write_identity:
        identity = True
    if args.no_write_identity:
        identity = False
    result = verify(
        target,
        runs_root=runs_root,
        persist_session=persist,
        write_identity=identity,
        start=not args.no_start,
        mode=args.mode,
        llm=True if args.llm else None,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
    )
    print(format_verify_summary(result["verdict"], result["run_dir"]))
    emit_ci(result["verdict"], result["run_dir"])
    req = result["verdict"]["requirements"][0]
    return exit_code(req["verdict"])


def cmd_explain(args: argparse.Namespace) -> int:
    search = Path(args.path).resolve()
    try:
        run_dir = resolve_run(args.run, search)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text, code = explain_text(run_dir, args.id)
    print(text)
    return code


def cmd_diff(args: argparse.Namespace) -> int:
    search = Path(args.path).resolve()
    try:
        left = resolve_run_arg(args.left, search)
        right = resolve_run_arg(args.right, search)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    runs_root = Path(args.out).resolve() if args.out else search / ".opentruth" / "runs"
    result = diff_runs(left, right, runs_root)
    print(format_verify_summary(result["verdict"], result["run_dir"]))
    emit_ci(result["verdict"], result["run_dir"])
    req = result["verdict"]["requirements"][0]
    return exit_code(req["verdict"])


def cmd_pack(args: argparse.Namespace) -> int:
    search = Path(args.path).resolve()
    try:
        run_dir = resolve_run(args.run, search)
        dest = Path(args.out).resolve() if args.out else Path(f"{run_dir.name}.zip").resolve()
        path = pack_run(run_dir, dest)
    except (FileNotFoundError, IntegrityError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return pack_error_exit(exc)
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opentruth", description="Independent software verification.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    verify_p = sub.add_parser("verify", help="run independent proof")
    verify_p.add_argument("--path", default=".", help="directory with requirements.yaml and opentruth.yaml")
    verify_p.add_argument("--out", default=None, help="runs directory (default: <path>/.opentruth/runs)")
    verify_p.add_argument(
        "--mode",
        choices=("browser", "api", "state"),
        default="browser",
        help="browser proof (M1), API proof (M2), or state/invariant proof (M3)",
    )
    verify_p.add_argument("--no-start", action="store_true", help="do not spawn the declared start command")
    verify_p.add_argument(
        "--persist-session",
        action="store_true",
        help="set MINIAUTH_PERSIST_SESSION=1 (fixture: disable planted bug)",
    )
    verify_p.add_argument(
        "--no-persist-session",
        action="store_true",
        help="set MINIAUTH_PERSIST_SESSION=0 (fixture default)",
    )
    verify_p.add_argument(
        "--write-identity",
        action="store_true",
        help="set MINIAUTH_WRITE_IDENTITY=1 (fixture: disable planted identity gap)",
    )
    verify_p.add_argument(
        "--no-write-identity",
        action="store_true",
        help="set MINIAUTH_WRITE_IDENTITY=0 (fixture default)",
    )
    verify_p.add_argument(
        "--llm",
        action="store_true",
        help="ask an LLM to propose plan.json only (never verdict.json); falls back if the model is down",
    )
    verify_p.add_argument(
        "--llm-model",
        default=None,
        help="chat model (default: OPENTRUTH_LLM_MODEL or gpt-4o-mini). Prefer a different model than the builder.",
    )
    verify_p.add_argument(
        "--llm-base-url",
        default=None,
        help="OpenAI-compatible base URL (default: OPENTRUTH_LLM_BASE_URL)",
    )
    verify_p.set_defaults(func=cmd_verify)

    explain_p = sub.add_parser("explain", help="walk the evidence graph")
    explain_p.add_argument("id", help="R-*, C-*, A-*, O-*, or E-*")
    explain_p.add_argument("--path", default=".", help="directory that contains .opentruth/runs")
    explain_p.add_argument("--run", default=None, help="run directory or id path")
    explain_p.set_defaults(func=cmd_explain)

    diff_p = sub.add_parser("diff", help="compare two sealed runs (change/diff proof)")
    diff_p.add_argument("left", help="older run directory or run id")
    diff_p.add_argument("right", help="newer run directory or run id")
    diff_p.add_argument("--path", default=".", help="directory that contains .opentruth/runs")
    diff_p.add_argument("--out", default=None, help="runs directory for the diff evidence (default: <path>/.opentruth/runs)")
    diff_p.set_defaults(func=cmd_diff)

    pack_p = sub.add_parser("pack", help="zip a sealed run for a CI artifact")
    pack_p.add_argument("--path", default=".", help="directory that contains .opentruth/runs")
    pack_p.add_argument("--run", default=None, help="run directory or id path (default: latest)")
    pack_p.add_argument("--out", default=None, help="zip path or directory (default: ./<run-id>.zip)")
    pack_p.set_defaults(func=cmd_pack)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    code = args.func(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
