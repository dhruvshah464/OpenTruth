# OpenTruth product report

**Date:** 27 August 2026  
**Audience:** anyone who needs the full picture without living in the code  
**Related:** protocol spec in [`../ideas/Prove.md`](../ideas/Prove.md)

OpenTruth is an **open verification protocol** for independently establishing software requirements from executable evidence.

The product vision remains: independently verify whether AI-generated software actually works. That is the use case that made the gap urgent. The protocol is broader. The builder may be an AI or a human. AI is the accelerator for the problem; it is not the reason the protocol exists.

```
AI-built (or human-built) software
        ↓
OpenTruth
        ↓
independent verification
        ↓
evidence
        ↓
verdict
```

---

## Milestone

> **v0.1 proof loop is established; v0.2 Verification IR is implemented; the core proof machinery remains unchanged.**

That is the transition. OpenTruth now has a coherent **protocol** story, not only an implementation story.

**Headline proof of correctness is reproducible falsification**, not a test count. Pytest (77 passed, 3 Chromium skipped) is useful engineering evidence. What makes `v0.1.0-m1` meaningful is the MiniAuth behavioral contract below.

**Central architecture:** the planner can change; this notebook machinery does not. Do not let the Verification IR become an excuse to redesign `plan.json` or the evidence system.

---

## Where the lab stands today

| Item | Status |
|---|---|
| Reproducible MiniAuth falsification (planted / fixed / diff) | Established — this is the v0.1.0-m1 contract |
| Proof kinds (browser, API, state, diff, CI, LLM-plan) | 6 / 6 shipped |
| Verification IR (`verification.version: 1`) | Implemented as v0.2 — compiles into existing `plan.json` |
| Core proof machinery (runners, A/O/E, seal, E-only verdict) | Unchanged |
| Git tag `v0.1.0-m1` | Cut at `fd5eff4` — MiniAuth freeze, not the IR commits on `main` |
| Product principle | **Complex protocol. Simple interface.** Named; interfaces not built beyond CLI / Action / MiniAuth console |
| v0.3 generic app (IR, no expander) | Next **engine** experiment — not started this pass |

Supporting engineering evidence: 77 tests passed (`pytest -m "not browser"`); 3 Chromium tests skipped on purpose; 80 collected. Do not treat that count as the headline.

---

## Protocol boundary

```
What is being claimed?
        │
        ▼
requirements.yaml
        │
        ▼
How should it be checked?
        │
        ▼
Verification IR
        │
        ▼
What actually executes?
        │
        ▼
plan.json
        │
        ▼
What actually happened?
        │
        ▼
A / O / E evidence
        │
        ▼
Can the evidence still be trusted?
        │
        ▼
hash / seal
        │
        ▼
What does the evidence establish?
        │
        ▼
verdict
```

Planners (declared IR, LLM, MiniAuth `expand()`) all land in the same `plan.json`. Runners and assertions write A/O/E. Seal, then verdict. That is the architecture to protect.

---

## Protocol core vs product experience

The protocol does not change so that a founder can use OpenTruth. The **interface around the protocol** must.

**Product principle:** Complex protocol. Simple interface.

A founder should not have to understand Python, YAML, Hatch, `plan.json`, or the evidence graph before the idea makes sense. They should understand:

```
1. Tell OpenTruth what "done" means.
2. Tell it where the application is.
3. Press Verify.
4. Inspect the evidence.
```

Everything else stays behind the interface. Internally the protocol remains hard: independent execution, sealed evidence, deterministic verdicts.

### What is being verified

The object of proof is the **running system**, not the repository.

```
                    SYSTEM UNDER TEST
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           source       runtime       data
              │            │            │
              └────────────┼────────────┘
                           ▼
                      observable
                       behavior
```

Source is supporting context. OpenTruth verifies observable behavior of localhost, staging, a container, or (later) a declared URL. “Repo verification” is the wrong mental model.

### Control surfaces, not engines

```
                OpenTruth Protocol
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
        CLI         GitHub       Web UI
                       Action
          │            │            │
          └────────────┼────────────┘
                       ▼
                 same verifier
                       │
                       ▼
                 same evidence
                       │
                       ▼
                  same verdict
```

The sealed run is the source of truth. CLI, the GitHub Action, and the local site are **control surfaces**. The website must not become a giant agent that *is* the proof. Today’s console at `:8787` drives MiniAuth through the same engine as `opentruth verify`.

### The trap

Do not run the builder’s tests and call that proof.

```
Cursor says "here are the tests I wrote"
        ↓
OpenTruth runs them
        ↓
PROVEN          ← still trusting the builder
```

The AI may **describe** the application (declarations only). OpenTruth retains authority over what constitutes proof: requirement → verification model → independent actions → independent observations → evidence → verdict.

### Acquisition loop (named, not hosted)

```
AI coding agent
      ↓
"Prepare this application for independent OpenTruth verification"
      ↓
declarations only (opentruth.yaml, requirements.yaml, optional IR)
      ↓
OpenTruth runs outside the agent
      ↓
evidence + verdict
      ↓
agent may fix; OpenTruth re-verifies
```

Copy-paste prompt: [`prompts/prepare-for-opentruth.md`](prompts/prepare-for-opentruth.md). It must not say “install OpenTruth into this repo” or “make the project use OpenTruth.” The builder prepares an adapter layer. The verifier stays an independent executable.

### Three future targets (not implemented)

| Target | Shape | When |
|---|---|---|
| Local application | `opentruth verify --path ./my-app` | **Now** (needs declared YAML; MiniAuth expander or IR) |
| Deployed application | local `opentruth verify --url https://…` | v0.5 — user-controlled install, remote target; **no hosted crawler** |
| Source + runtime | `--repo` + `--url` | After URL exists — this source produced this running system |

A public `https://opentruth.dev/verify` scanner is refused until isolation, SSRF, credentials, and abuse are designed. First URL capability is local OpenTruth against a declared remote target.

---

## In plain words

### The problem

Coding assistants now build apps and then say “done.” A person is left trusting that speech. Tests the assistant just wrote live in the same project it edited, so the builder can quietly weaken them. Nearby tools check chat logs, generate more tests, or do math proofs. The empty slot is simpler: **did the running product actually do the thing?**

The same question applies when a human built the software. OpenTruth answers it with executable evidence, not with the builder’s word.

OpenTruth is that inspector. Analogy: a contractor says the house lock works. OpenTruth is a second person who walks to the door, tries the key, walks away, comes back, and writes a signed notebook. If someone later changes a page, the signature no longer matches.

### The one rule

The verifier is not the builder. OpenTruth never writes tests into the app’s files. Evidence lives only in a sealed run folder.

`PROVEN` is not merely that the folder exists. It is:

```
PROVEN
  = required verification coverage executed
  + required assertions established
  + evidence chain intact
  + seal/hash validation succeeds
```

A stranger can walk `R-* → C-* → A-* / O-* / E-*` and the hashes still match. That is defensible. A green log line the builder printed is not.

“Planned” checks means **protocol-defined coverage** (declared constraints, and when present the Verification IR), not “whatever a planner happened to generate.” The IR is what begins making that distinction real.

**The planner can change; this notebook machinery does not.**

### The five possible answers

| Word | In plain language |
|---|---|
| `PROVEN` | Required coverage was executed, required assertions hold, the evidence chain is intact, and the seal/hash still matches. |
| `PARTIALLY_PROVEN` | The main path works; at least one extra check fails. MiniAuth does this when login works but the session dies on refresh. |
| `FAILED` | The main thing itself was seen not to work. |
| `NOT_PROVEN` | Not enough evidence to establish the claim (thin coverage, or a claimed fix did not establish the requirement). **Not the same as FAILED.** |
| `INCONCLUSIVE` | Could not look (app down, timeout, invalid plan). **Not a pass and not a product failure. Not the same as FAILED.** |

`NOT_PROVEN ≠ FAILED`. `INCONCLUSIVE ≠ FAILED`. That prevents the verifier from confusing “the software is broken” with “we do not possess enough evidence to establish the claim.” That distinction is essential for a verification protocol.

### The practice house: MiniAuth

MiniAuth is a tiny sign-up / sign-in app shipped with OpenTruth. It mostly works. Two faults are planted on purpose so the inspector has something true to catch:

1. After login, refresh often sends you back to login (unless `MINIAUTH_PERSIST_SESSION=1` / `--persist-session`).
2. A database “identity” row may be skipped even when the screen looks fine (unless `MINIAUTH_WRITE_IDENTITY=1` / `--write-identity`).

Turn the plants off and the same inspector says **PROVEN**. That is how we know the engine is honest, not optimistic.

### The six kinds of looking

| Layer | What the inspector does |
|---|---|
| M1 Browser | Uses the screens like a person: fill Email, click Create account. |
| M2 API | Calls the declared HTTP routes directly (signup, login, me). |
| M3 State | After the app claims success, reads the SQLite database. |
| M4 Change | Compares two sealed notebooks: what improved, held, or got worse. |
| M5 Continuous | Same command in GitHub Actions. Exit 0 only if PROVEN. Uploads the zip. |
| M6 AI plan | A different model may suggest the steps. It cannot write the verdict. |

### What changed after those six layers

The six layers proved the inspector can produce an auditable verdict. The next step was not a shop, a dashboard, or a second demo app. It was a declared language for “how to check,” called the **Verification IR**. MiniAuth still uses the old auth-shaped planner so the original proof does not drift. Other apps can now write typed steps (`http_request`, `assert`, …) that compile into the same plan the runners already execute.

**Do not let the IR become an excuse to redesign `plan.json` or the evidence system.**

```
                     PLANNERS
        ┌──────────────┼──────────────┐
        │              │              │
   declared IR        LLM       MiniAuth expand()
        │              │              │
        └──────────────┼──────────────┘
                       ▼
                    plan.json
                       │
                 ┌─────┴─────┐
                 ▼           ▼
              runners     assertions
                 │           │
                 └─────┬─────┘
                       ▼
                     A/O/E
                       ▼
                     seal
                       ▼
                    verdict
```

### The notebook (evidence graph)

IDs are labels in the notebook:

```
R-1  requirement (“a user can create an account and sign in”)
 ├── C-0  happy path
 ├── C-1  duplicate emails rejected
 ├── C-2  invalid password rejected
 ├── C-3  session persists after refresh   ← planted fail on default MiniAuth
 └── C-4  unauthorized access rejected
```

- `A-*` — an action the inspector took  
- `O-*` — what it observed  
- `E-*` — an assertion citing observations  

Only `E-*` feed the verdict. The planner can change; this notebook machinery does not.

Default MiniAuth API run: C-0, C-1, C-2, C-4 PASS · C-3 FAIL (session). Planted → claimed fix: C-3 IMPROVED on the diff. **Live console run ids change every session; the outcomes do not.**

### What this is not

It is not a login SaaS. The local site is a **control surface** for the MiniAuth demo, not a different verifier. It is not a marketplace of verifiers. It does not read an unknown company repo and invent requirements. It does not run the builder’s tests. You (or a coding agent) declare how to start the app and what “done” means. Then the independent inspector runs.

---

## What works

The thing that makes `v0.1.0-m1` meaningful is this **specific behavioral contract** — reproducible falsification, not a test count:

```
MiniAuth planted
→ PARTIALLY_PROVEN
→ C-3 FAIL

MiniAuth fixed
→ PROVEN

planted → fixed
→ PROVEN
→ C-3 IMPROVED

seal/hash
→ valid

verdict
→ E-* only
```

Shipped and frozen in place:

- [x] M1 Browser proof — Playwright; missing controls are INCONCLUSIVE
- [x] M2 API proof — declared HTTP routes only
- [x] M3 State proof — SQLite after HTTP; identity-row plant
- [x] M4 Diff proof — improved / regressed / unchanged
- [x] M5 CI — exit contract, pack zip, GitHub Action (pack skipped if install never happened)
- [x] M6 LLM may write `plan.json` only; CLI, Action, and console
- [x] Product site + live MiniAuth console at `:8787`
- [x] One-click planted → claimed fix → sealed diff
- [x] v0.1.0-m1 MiniAuth acceptance contract in pytest (outcomes, not live run ids)
- [x] v0.2 Verification IR — versioned typed steps compile to existing `plan.json`
- [x] Coverage law — every declared `C-*` must produce assertion evidence or the requirement is `NOT_PROVEN`

### v0.1.0-m1 acceptance contract (permanent)

Clones get new run ids. The contract is the **outcomes** below. Future protocol work must not change them accidentally. Encoded in `tests/test_m1_contract.py`.

| What you run | Overall word | What the checks say |
|---|---|---|
| `verify` MiniAuth API (planted) | `PARTIALLY_PROVEN` | C-3 fail; other C-* pass. Seal/hash pass. Verdict from E-* only. |
| same with `--persist-session` | `PROVEN` | All C-* pass. |
| `diff` planted → persist-session | `PROVEN` | C-3 IMPROVED; others UNCHANGED. |

### MiniAuth: yes, no, and “could not look”

| Mode | Default (planted) | Plant off | App unreachable |
|---|---|---|---|
| browser | PARTIALLY_PROVEN (C-3 session) | PROVEN (`--persist-session`) | INCONCLUSIVE |
| api | PARTIALLY_PROVEN (C-3 session) | PROVEN (`--persist-session`) | INCONCLUSIVE |
| state | PARTIALLY_PROVEN (identity row) | PROVEN (`--write-identity`) | INCONCLUSIVE |
| diff planted → fixed | — | PROVEN (C-3 IMPROVED) | — |
| diff fixed → planted | FAILED (C-3 REGRESSED) | — | — |

### Verification IR (what just shipped)

An app may declare `verification.version: 1` with typed steps. OpenTruth parses, validates, substitutes `{{actor.email}}` / `{{actor.password}}`, and compiles into the same `plan.json` the runners already understand. MiniAuth’s default YAML has **no** `verification` block, so the original demo still uses the auth expander.

| If this happens | What OpenTruth does |
|---|---|
| `verification.version: 1` is present | Compile IR. Ignore `--llm` and the auth expander. |
| No verification block | If `--llm`, sanitize a model plan; else `expand()` for MiniAuth-shaped apps. |
| Unknown version, shell, unknown C-* | Reject. Do not silently expand. Run is INCONCLUSIVE with `ir_error`. |
| A C-* has no assert in the plan | Stamp `uncovered_constraints`. Write E-* `coverage` = inconclusive. Requirement `NOT_PROVEN` if the happy path still passed. |
| Model returns `"verdict": "PROVEN"` | Dropped. Verdict still rolled from E-* only. |

### Earlier live console notes (27 Aug 2026)

These ids were **one session**. They are examples, not the freeze contract.

| What we ran | IDs that day | Result |
|---|---|---|
| Console: Run full proof (API) | `61ba02bf` → `37b5ba42` → `77b7ba9c` | PARTIAL, PROVEN, PROVEN (C-3 IMPROVED) |
| Console: LLM plan checkbox, no API key | `c210ac18` | PARTIALLY_PROVEN · planner deterministic · requested llm · key missing |

### M6 in one sentence

You may ask another model to propose the steps. If it is down, if the key is missing, if it tries `shell` / `DROP TABLE`, or if it returns `"verdict": "PROVEN"`, OpenTruth still inspects the app itself. A plan that only covers the happy path cannot skip the rest into PROVEN — it becomes `NOT_PROVEN`.

---

## How to use it

There is no login website. An outside user installs the engine on their machine or in CI. The local site at `http://127.0.0.1:8787` is a **control surface** (company pages plus a console bound to MiniAuth). It is the same verifier as the CLI, not a cloud account and not a different engine.

### 1. Try the practice house

| Command | What you should see |
|---|---|
| `pip install -e ".[dev]"` | Package `opentruth` installed |
| `playwright install chromium` | Needed only for browser proof |
| `opentruth verify --path examples/miniauth --mode api` | PARTIALLY_PROVEN · C-3 FAIL |
| `opentruth explain C-3 --path examples/miniauth` | Walk: GET `/api/me` after login is 401 |
| `opentruth serve` | Site at `http://127.0.0.1:8787` |

### 2. Point it at another app

Paste [`prompts/prepare-for-opentruth.md`](prompts/prepare-for-opentruth.md) into Cursor, Claude, or Gemini. The coding agent may create **declarations only**:

- `opentruth.yaml` — how to start, health URL, routes
- `requirements.yaml` — one English requirement plus constraints
- optional `verification` block (Verification IR)

Then **you** run `opentruth verify` **outside** the agent. The prompt forbids writing verdicts, evidence, or claiming the app is verified.

MiniAuth can omit a `verification` block and still work, because the built-in planner understands signup / login / session / unauthorized. An app that is **not** auth-shaped should declare Verification IR steps instead of hoping the expander guesses.

Declared IR (protocol path): `verification.version: 1`, then steps with `id`, `constraint`, and one kind (`http_request`, `assert`, `navigate`, `fill`, `click`, `sql_query`, …). Unknown version or `shell` is rejected.

### 3. Continuous inspection (CI)

GitHub Action uses this repo. Job fails unless PROVEN (exit 0). INCONCLUSIVE exits 2. Other verdicts exit 1. Tampered pack exits 3. If install failed, pack is skipped so CI does not fail on a missing binary. The sealed zip is uploaded when it exists.

| Action input | Meaning |
|---|---|
| `path` | Folder with the two yaml files |
| `mode` | `browser`, `api`, or `state` |
| `llm` | `true` = ask a model for `plan.json` only |
| `llm-model` | Prefer a different model than the builder |
| env `OPENTRUTH_LLM_API_KEY` | Job secret; never stored in the Action |

### 4. M6 for an outside user

```bash
export OPENTRUTH_LLM_API_KEY=…
opentruth verify --path examples/miniauth --mode api --llm --llm-model not-the-builder
```

Same checkbox on the console. Same `llm: true` on the Action. Default verify without `--llm` never calls a model. If the YAML already has `verification.version`, the declared IR wins and the model is not asked.

---

## Working conditions

### What must be true to run

| Condition | Value |
|---|---|
| Python | 3.11 or newer (CI uses 3.12) |
| Install | `pip install -e ".[dev]"` |
| Browser proof | `playwright install chromium` |
| Package | `opentruth` 0.1.0 · Apache-2.0 |
| Site | `http://127.0.0.1:8787` via `opentruth serve` |
| Console subject | `examples/miniauth` only |
| Declared files | `opentruth.yaml` + `requirements.yaml` (state: `requirements-state.yaml`) |
| MiniAuth default YAML | No `verification` block — expander compatibility path |
| LLM | Optional key; fallback if missing or down |
| CI Python | 3.12 in GitHub Actions |
| Release tag | `v0.1.0-m1` at `fd5eff4` (MiniAuth freeze; IR is later on `main`) |

### Planner precedence (deterministic)

1. Declared Verification IR, if `verification` is present
2. LLM proposal if `--llm`, still allowlisted
3. Auth-shaped `expand()` (MiniAuth convenience)

The model can influence what gets attempted. It cannot declare what is true. Runners, A/O/E, seal, and `verdict.json` from E-* stay the same whichever planner ran.

### Coverage law

Every declared check (`C-*`) must have an **assert** in the compiled plan and must produce assertion evidence. Action-only steps (a request with no assert) do not count. Missing coverage is written as an `E-*` record (`check: coverage`, result `inconclusive`) and listed on `plan.json` as `uncovered_constraints`. If the happy path still passed, the requirement is **NOT_PROVEN** — never silent PROVEN.

### How a verdict is computed

Each check looks at its assertions: no assertions → inconclusive; any fail → fail; else any inconclusive → inconclusive; else all pass → pass.

The requirement:

- happy path (`C-0`) fails → `FAILED`
- happy path cannot be observed → `INCONCLUSIVE`
- happy path passes and every other check passes → `PROVEN`
- happy path passes and something else fails → `PARTIALLY_PROVEN`
- happy path passes and something else is inconclusive → `NOT_PROVEN`

Confidence = passed / conclusive. `INCONCLUSIVE` is left out of that fraction so a crash cannot look like a product bug.

### CI exit contract

| Exit code | When |
|---|---|
| 0 | PROVEN |
| 1 | PARTIALLY_PROVEN, FAILED, NOT_PROVEN |
| 2 | INCONCLUSIVE |
| 3 | Tampered pack / INTEGRITY FAILED |

### What sits in a sealed run

Folder `.opentruth/runs/<id>/` (the website uses `.opentruth/web-runs/`). JSONL files only grow; IDs are never reused. `manifest.json` is written last and hashes every file.

| File | Job |
|---|---|
| `manifest.json` | Seal and SHA-256 of everything |
| `requirements.json` | Frozen requirement and checks (R-* / C-*) |
| `plan.json` | Steps. Planner is `ir`, `llm`, or `deterministic`. May list `uncovered_constraints`. |
| `actions.jsonl` | What the inspector did (A-*) |
| `observations.jsonl` | What it saw (O-*) |
| `assertions.jsonl` | Checks citing observations (E-*) |
| `screenshots/` `network/` `artifacts/` | Files those records point at |
| `verdict.json` | Rolled up from E-* only, then sealed |

---

## Protocol laws

[`../ideas/Prove.md`](../ideas/Prove.md) is the protocol specification. Code and tests follow it. Do not weaken these in implementation.

| # | Law | In plain language |
|---|---|---|
| 1 | Verifier ≠ Builder | The inspector never writes tests into the app it is judging. |
| 2 | Verdict ≠ model opinion | Only recorded checks decide PROVEN. A model cannot say it. |
| 3 | Evidence is inspectable | A stranger can walk requirement → check → action → observation → assertion. |
| 4 | Evidence is integrity-protected | After the seal, a changed file is INTEGRITY FAILED. The stored verdict is no longer evidence. |
| 5 | Failed verification ≠ software failure | Could not look is INCONCLUSIVE, not FAILED. |
| 6 | Inconclusive ≠ proven | A timeout cannot pad the pass rate. |
| 7 | Requirements are explicit | You declare start + health + what done means. No secret repo scanning. |
| 8 | Verdicts are reproducible | Same fixture, same flags, same words. Run ids may differ. |
| 9 | AI may propose; machinery decides | A model may suggest steps. Compiler, runner, evidence, and verdict engine decide truth. |
| 10 | Every claim points to evidence | A check with no executable coverage cannot vanish into a pass. |
| 11 | The planner can change; the notebook does not | IR, LLM, and expand() all compile into the same `plan.json`, runners, A/O/E, seal, and E-only verdict. |

### Five layers that must stay distinct

| Layer | What it is | What it is not |
|---|---|---|
| Requirement language | English + C-* list in YAML | Not the steps that will run |
| Verification IR | Versioned, typed steps | Not the runner’s `plan.json` yet |
| Execution plan | `plan.json` the runners already execute | Not a verdict |
| Evidence | A / O / E records + blobs | Not a dashboard |
| Verdict | Rolled from E-* only | Not a model’s last sentence |

### Who is allowed to do what

| Actor | May | May not |
|---|---|---|
| Human / YAML | Declare requirement and IR | Declare the software true |
| LLM | Propose `plan.json` | Write `verdict.json` |
| IR compiler | Validate and compile | Execute the app |
| Runner | Operate browser / HTTP / SQL | Invent a pass |
| Evidence store | Record reality, then seal | Rewrite after seal |
| Verdict engine | Roll E-* → C-* → R-* | Ask the model what to print |

**The planner can change; the proof machinery does not.** That is why Verification IR was allowed, and why MiniShop, adversarial suites, and git-range products wait. New planners still land in the same sealed notebook. New interfaces (prompt, later `--url`, later web) must call that notebook — they must not replace it.

---

## Full list

### Commands

| Command | Job |
|---|---|
| `opentruth verify` | Run a proof into a sealed folder |
| `opentruth explain` | Walk the graph; refuse a tampered pack |
| `opentruth diff` | Compare two sealed runs |
| `opentruth pack` | Zip a sealed run for CI |
| `opentruth serve` | Company site + live console |

### Product artifacts (not the verifier)

| Path | Job |
|---|---|
| `prompts/prepare-for-opentruth.md` | Copy-paste prompt: builder creates declarations only |

### Website pages

| Address | Job |
|---|---|
| `/` | Thesis, six layers, live engine counts |
| `/engine` | Proof layers + Verification IR |
| `/evidence` | Sealed notebook model |
| `/console` | Live proof, loop, graph, explain, pack, M6 checkbox |
| `/docs` | CLI, CI, IR, M6 for outside users |
| `/company` | Lab position |
| unknown page | 404: No evidence on this path |

### HTTP API

| Method | Path | Job |
|---|---|---|
| GET | `/api/v1/health` | ok, version, run count, latest, llm configured? |
| GET | `/api/v1/product` | Name, principle, six layers |
| GET | `/api/v1/runs` | Last 24 sealed web runs |
| POST | `/api/v1/verify` | One MiniAuth proof (optional llm) |
| POST | `/api/v1/loop` | Planted + fix + diff |
| POST | `/api/v1/diff` | Compare two distinct run ids |
| GET | `/api/v1/runs/{id}` | Graph, files, plan, integrity |
| GET | `/api/v1/runs/{id}/explain/{node}` | Walk one label |
| GET | `/api/v1/runs/{id}/pack` | Download zip |
| GET | `/api/v1/runs/{id}/file/…` | Screenshot / network / artifact |

### Engine modules

| File | Job |
|---|---|
| `requirement.py` | Load English YAML; pass through optional verification |
| `ir.py` | Parse → validate → normalize → compile Verification IR |
| `discovery.py` | Declared start / health / routes |
| `planning.py` | Built-in auth-shaped expander |
| `llm.py` | Optional plan proposal + allowlist; IR still wins |
| `engine.py` | One verify; coverage gaps become E-* |
| `runners/browser.py` | M1 |
| `runners/http.py` | M2 |
| `runners/state.py` | M3 |
| `runners/process.py` | Start and stop the app |
| `assertions.py` | Turn observations into E-* |
| `store.py` | Append-only folder + seal |
| `graph.py` | In-memory notebook |
| `verdicts.py` | Roll-up and confidence |
| `diff.py` | M4 |
| `explain.py` | Walker |
| `ci.py` | Exit codes and zip |
| `cli.py` | Commands |
| `server.py` | Site + live engine |

### Automated tests by surface (supporting evidence, 27 Aug 2026)

Not the headline. Headline is the MiniAuth falsification contract. These counts are engineering coverage of that machinery: 80 collected · 77 passed with `-m "not browser"` · 3 Chromium tests deselected.

| Surface | Test functions |
|---|---|
| Core (assertions, store, verdicts, planning) | 13 |
| M1 browser | 4 |
| M2 API | 3 |
| M3 state | 3 |
| M4 diff | 8 |
| M5 CI | 10 |
| M6 LLM plan | 12 |
| Verification IR | 19 |
| M1 contract | 4 |
| Site | 4 |

---

## Future tasks

The remaining major question is no longer “can OpenTruth work?” That is demonstrated. Two questions sit in front:

1. **Protocol:** does OpenTruth generalize beyond MiniAuth? (IR, no auth expander, a different small app.)
2. **Product:** can a founder give OpenTruth a running app and a claim without learning the notebook? (Interfaces around the same verifier.)

Usability is **named early**. It is not an excuse to change runners, seal, or `verdict.json`. Versions are not sacred. Product usability does not wait until the protocol is “complete,” but this pass is **docs only** — no `--url`, no second demo app, no hosted scanner.

Treat `v0.1.0-m1` as the **frozen falsifiable experiment**. Treat IR as **v0.2**. The prompt in `prompts/` is the first product-layer artifact.

### Roadmap (protocol core unchanged; interfaces evolve)

| Version | Task | Status |
|---|---|---|
| v0.1.0-m1 | Frozen MiniAuth falsifiable experiment | Done (`v0.1.0-m1` → `fd5eff4`) |
| v0.2 | Versioned Verification IR compiling into existing `plan.json` | Done |
| v0.3 | Independent generic app verification (IR only, no auth expander) | Next **engine** experiment — not started |
| v0.4 | Zero-config bootstrap: “Prepare this application for independent OpenTruth verification” | Prompt shipped as docs; no CLI/Action change |
| v0.5 | Local `verify --url` / deployed-app verification (user-controlled install; no hosted crawler) | Not started |
| v0.6 | Adversarial verification (hostile inputs as declared campaigns) | Not started |
| v0.7 | Invariant verification as a first-class campaign, not a MiniAuth plant | Not started |
| v0.8 | Git / PR differential verification (e.g. `verify --base HEAD~1`) | Not started |
| v0.9 | AI-generated Verification IR (still never writes `verdict.json`) | Not started |
| v1.0 | OpenTruth Protocol — same verifier behind CLI, Action, and future web | Not started |
| after that | Benchmark apps (MiniShop and friends); `--repo` + `--url` source→runtime chain | Not started |

### Do now if you want a frozen release

- [x] Confirm git tag `v0.1.0-m1` (and push if you want it on the remote)
- [ ] Optional extra CI job for the 3 Chromium tests (needs Playwright on the runner)
- [ ] Publish `opentruth` 0.1.0 to PyPI if outsiders should `pip install` without cloning

### Frozen (named so they stay off the board)

- Automatic requirement discovery — inventing what to check by reading the repo
- Unfamiliar repository analysis — “understand any codebase”
- Multi-agent verification — a crowd of AIs arguing
- Production observability — dashboards on live traffic
- Verification marketplaces — buying/selling proofs
- Enterprise dashboards — a SaaS UI as the product
- Accounts, billing, or hosted `serve` — stay local
- Public URL scanning service (`opentruth.dev/verify`) — SSRF, credentials, isolation, abuse; local `--url` comes first

### Also refused

| Idea | Why not |
|---|---|
| Write tests into the target app | Then the builder owns the proof |
| Run the builder’s tests and stamp PROVEN | Still trusting the builder |
| Crawl OpenAPI / fuzz APIs as a product | M2 is declared routes only |
| A generic invariant language / DB fuzzer right now | Wait for v0.7; M3 today is one runner |
| Crawl every git commit as a product | Wait for v0.8; M4 today is two sealed runs |
| Hosted verification in the cloud | M5 is the CLI in CI; website is a control surface |
| Let an LLM write `verdict.json` | M6 / v0.9 may write plans only |
| Treat raw YAML as the IR | Requirement language ≠ Verification IR ≠ `plan.json` |
| “Install OpenTruth into the app” as the bootstrap | The builder must not modify the verifier |

### Risks that stay true

| Risk | What we do about it |
|---|---|
| Screens are brittle | Use labels and roles; missing control → INCONCLUSIVE, not invented CSS |
| A model would make proof fuzzy | Default path has no model; IR/LLM cannot write the verdict |
| Temptation to scan unknown repos | Reads declared yaml only; freeze named |
| Someone edits the notebook | `explain` and `pack` refuse; INTEGRITY FAILED |
| A crash looks like a product bug | INCONCLUSIVE is not in the confidence fraction |
| A check exists but is never executed | Coverage E-* + NOT_PROVEN; cannot silently disappear |
| IR work accidentally “fixes” MiniAuth | v0.1.0-m1 pytest contract: planted stays PARTIAL |

---

## The boundary, once more

```
declared environment + requirement
        ↓
Verification IR  or  LLM (sanitized)  or  auth expander
        ↓
plan.json
        ↓
existing runners (browser / API / state)
        ↓
A / O / E notebook
        ↓
verdict.json  (from E-* only)
        ↓
seal manifest.json
        ↓
opentruth explain walks the graph
```

The website is that engine **served**, not a second verifier. If a change does not make **PROVEN** more defensible, it waits. If a change only makes the protocol easier to reach without weakening independence, it belongs in the **product layer**.

---

## Assessment

The remaining major question is no longer “Can OpenTruth work?” You have demonstrated that. Next: does the protocol generalize beyond MiniAuth, and can the **product layer** hide the notebook without owning the proof. The Verification IR is the bridge. The bootstrap prompt is the first interface artifact. Neither may compromise M1.

| Foundation | Status |
|---|---|
| Idea | Yes |
| Core thesis | Yes |
| Falsifiable demo | Yes |
| Independent verifier | Yes |
| Evidence graph | Yes |
| Cryptographic sealing | Yes |
| Conservative verdicts | Yes |
| CI integration | Yes |
| LLM separation | Yes |
| Versioned Verification IR | Yes |
| Protocol/document boundary | Yes |
| Protocol vs product distinction | Yes (this pass; docs only) |
| Prepare-for-OpenTruth prompt | Yes (`prompts/prepare-for-opentruth.md`) |
| Reproducible release target | Yes (`v0.1.0-m1` at `fd5eff4`) |
