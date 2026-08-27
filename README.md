# OpenTruth

Independent verification that software **actually satisfies a requirement**.

Not “did the AI write code?” — **did the built system do the thing in reality?**

OpenTruth is the verifier, never the builder. It does not write tests into the target
repository. It operates the application, records an immutable evidence graph, and
returns `PROVEN` / `PARTIALLY_PROVEN` / `FAILED` / `NOT_PROVEN` / `INCONCLUSIVE`.

`PROVEN` is defensible only if a stranger can walk `R-1 → C-3 → E-* → O-*` and the
file hashes still match. That sealed run directory *is* the product.

See [`../ideas/Prove.md`](../ideas/Prove.md) for the RFC, six proof layers, and the
post-M6 freeze (no dashboards, marketplaces, or “understand any repo”).

## Status

Milestone 1: **browser proof**. Milestone 2: **API proof**. Milestone 3: **state /
invariant proof**. Milestone 4: **change/diff proof**. Milestone 5: **continuous
verification**. Milestone 6: **AI-assisted planning** (`--llm` may write `plan.json`
only). Six proof layers shipped. Freeze: no dashboards, marketplaces, or
“understand any repo.”

## Quick start

```bash
pip install -e ".[dev]"
playwright install chromium
pytest
opentruth verify --path examples/miniauth
opentruth verify --path examples/miniauth --mode api
opentruth verify --path examples/miniauth --mode state
opentruth explain R-1 --path examples/miniauth
```

The MiniAuth fixture plants a session-persist bug. Default verify is
**PARTIALLY_PROVEN** (`C-3` fails). Disable the bug to see **PROVEN**:

```bash
opentruth verify --path examples/miniauth --persist-session
opentruth verify --path examples/miniauth --mode api --persist-session
opentruth verify --path examples/miniauth --mode state --write-identity
```

Compare a claimed fix against a prior sealed run:

```bash
opentruth verify --path examples/miniauth --mode api
opentruth verify --path examples/miniauth --mode api --persist-session
opentruth diff <before-run-id> <after-run-id> --path examples/miniauth
opentruth explain R-1 --path examples/miniauth
```

## Continuous verification

CI is the CLI, not a service. `PROVEN` exits 0; `INCONCLUSIVE` exits 2; everything
else exits 1. On GitHub Actions, `verify` writes job outputs and a step summary.
`opentruth pack` zips the sealed run for `actions/upload-artifact`.

```yaml
- uses: ./
  with:
    path: examples/miniauth
    mode: api
    persist-session: "true"
```

Or by hand:

```bash
opentruth verify --path examples/miniauth --mode api --persist-session
opentruth pack --path examples/miniauth --out opentruth-run.zip
```

This repo’s workflow (`.github/workflows/opentruth.yml`) runs `pytest -m "not browser"`
and the MiniAuth API proof with the planted bug disabled so the engine gate is **PROVEN**.

Optional: ask a *different* model than the builder to propose the plan. The verdict
is still rolled up from assertions.

```bash
export OPENTRUTH_LLM_API_KEY=...
opentruth verify --path examples/miniauth --mode api --llm --llm-model not-the-builder
```

If the model is down, verify falls back to the deterministic planner.

## Evidence layout

```
.opentruth/runs/<run-id>/
  manifest.json
  requirements.json
  plan.json
  actions.jsonl
  observations.jsonl
  assertions.jsonl
  screenshots/
  network/
  artifacts/
  verdict.json
```

## Principle

**Verifier ≠ Builder.** The same agent that wrote the feature is not the entity that
decides it works.
