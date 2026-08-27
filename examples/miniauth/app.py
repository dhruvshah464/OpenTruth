"""MiniAuth fixture: signup/login with a planted session-persist bug."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

PERSIST = os.environ.get("MINIAUTH_PERSIST_SESSION", "0") == "1"
WRITE_IDENTITY = os.environ.get("MINIAUTH_WRITE_IDENTITY", "0") == "1"
DB_PATH = Path(os.environ.get("MINIAUTH_DB", "miniauth.sqlite"))
COOKIE = "miniauth_session"

# token -> {email, seen_dashboard}
SESSIONS: dict[str, dict] = {}

app = FastAPI(title="MiniAuth")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, password_hash TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS identities (email TEXT PRIMARY KEY, user_email TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def _maybe_write_identity(conn: sqlite3.Connection, email: str) -> None:
    if not WRITE_IDENTITY:
        return
    conn.execute(
        "INSERT OR IGNORE INTO identities (email, user_email) VALUES (?, ?)",
        (email, email),
    )


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _page(title: str, body: str, notice: str = "") -> HTMLResponse:
    flash = f'<p class="notice">{notice}</p>' if notice else ""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
  <h1>{title}</h1>
  {flash}
  {body}
</body>
</html>"""
    return HTMLResponse(html)


def _form(action: str, button: str) -> str:
    return f"""
  <form method="post" action="{action}">
    <p>
      <label>Email
        <input type="email" name="email" autocomplete="username" required>
      </label>
    </p>
    <p>
      <label>Password
        <input type="password" name="password" autocomplete="current-password" required>
      </label>
    </p>
    <p><button type="submit">{button}</button></p>
  </form>
"""


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return _page(
        "MiniAuth",
        '<p><a href="/signup">Create account</a> · <a href="/login">Sign in</a></p>',
    )


@app.get("/signup", response_class=HTMLResponse)
def signup_get(request: Request) -> HTMLResponse:
    notice = request.query_params.get("notice", "")
    return _page("Create account", _form("/signup", "Create account") + '<p><a href="/login">Sign in</a></p>', notice)


@app.post("/signup")
def signup_post(email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    conn = _connect()
    try:
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, _hash(password)),
            )
            _maybe_write_identity(conn, email)
            conn.commit()
        except sqlite3.IntegrityError:
            return _page(
                "Create account",
                _form("/signup", "Create account"),
                "Email already registered",
            )
    finally:
        conn.close()
    return RedirectResponse("/login?notice=Account%20created", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request) -> HTMLResponse:
    notice = request.query_params.get("notice", "")
    if notice == "Account created":
        notice = "Account created"
    return _page("Sign in", _form("/login", "Sign in") + '<p><a href="/signup">Create account</a></p>', notice)


@app.post("/login")
def login_post(email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] != _hash(password):
        return _page(
            "Sign in",
            _form("/login", "Sign in"),
            "Invalid credentials",
        )
    token = secrets.token_hex(16)
    SESSIONS[token] = {"email": email, "seen_dashboard": False}
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(COOKIE, token, httponly=True)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    token = request.cookies.get(COOKIE)
    session = SESSIONS.get(token or "")
    if not session:
        return RedirectResponse("/login", status_code=303)
    if not PERSIST:
        if session.get("seen_dashboard"):
            return RedirectResponse("/login", status_code=303)
        session["seen_dashboard"] = True
    return _page(
        "Dashboard",
        f"<p>Signed in as {session['email']}</p><p><a href='/logout'>Sign out</a></p>",
    )


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


class Credentials(BaseModel):
    email: str
    password: str


def _session_from_request(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    return SESSIONS.get(token or "")


@app.post("/api/signup")
def api_signup(body: Credentials):
    email = body.email.strip().lower()
    conn = _connect()
    try:
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, _hash(body.password)),
            )
            _maybe_write_identity(conn, email)
            conn.commit()
        except sqlite3.IntegrityError:
            return JSONResponse({"error": "Email already registered"}, status_code=409)
    finally:
        conn.close()
    return JSONResponse({"email": email, "created": True}, status_code=201)


@app.post("/api/login")
def api_login(body: Credentials):
    email = body.email.strip().lower()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] != _hash(body.password):
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)
    token = secrets.token_hex(16)
    SESSIONS[token] = {"email": email, "seen_dashboard": False}
    response = JSONResponse({"email": email})
    response.set_cookie(COOKIE, token, httponly=True)
    return response


@app.get("/api/me")
def api_me(request: Request):
    session = _session_from_request(request)
    if not session:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not PERSIST:
        if session.get("seen_dashboard"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        session["seen_dashboard"] = True
    return {"email": session["email"]}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8471"))
    uvicorn.run(app, host="127.0.0.1", port=port)
