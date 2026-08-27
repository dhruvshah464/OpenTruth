# Prepare this application for independent OpenTruth verification

Copy everything below the line into Cursor, Claude, Gemini, or another coding agent.
Paste it in the repository of the **application to be verified**, not inside the OpenTruth engine.

This is a **declaration / adapter** prompt. It does not install OpenTruth into the app, does not modify the verifier, and does not produce a verdict.

---

You are preparing this application for **independent verification by OpenTruth**.

Do not claim that the application is verified.
Do not modify OpenTruth’s verifier, runners, evidence store, or verdict machinery.
Do not write tests into this repository that OpenTruth is supposed to “run as proof.”
Do not write verification results.
Do not mark requirements as passed.
Do not create or edit OpenTruth evidence files, `verdict.json`, sealed run directories, or hashes.

Inspect the application and create the **minimum OpenTruth declaration** needed to independently verify its **externally observable** requirements.

Create only:

- `opentruth.yaml` — how the application starts, its URL/port, health check, relevant API routes, required env, and (if applicable) how to find SQLite or equivalent durable state
- `requirements.yaml` — one English requirement plus explicit constraints (what “done” means)
- optional `verification` block (`verification.version: 1`) with typed steps if this app is not a MiniAuth-shaped signup/login app

Declare:

- how the application starts
- its URL/port
- relevant API routes
- required test accounts or fixtures (credentials as placeholders, not secrets committed)
- observable acceptance criteria

The builder may make the application **observable and declarable**. OpenTruth itself remains an independent executable run **outside** this session.

When finished, report **only what was declared** (file paths and a short summary of requirements and constraints). Do not print PROVEN, FAILED, or any verdict.
