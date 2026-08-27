"""MiniTodos fixture: create/list/complete with a planted complete-persist bug."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PERSIST = os.environ.get("MINITODOS_PERSIST_COMPLETE", "0") == "1"

# id -> {id, title, done}
TODOS: dict[str, dict[str, object]] = {}

app = FastAPI(title="MiniTodos")


class TodoCreate(BaseModel):
    id: str
    title: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/todos")
def create_todo(body: TodoCreate):
    title = body.title.strip()
    if not title:
        return JSONResponse({"error": "title required"}, status_code=400)
    todo_id = body.id.strip()
    if not todo_id:
        return JSONResponse({"error": "id required"}, status_code=400)
    if todo_id in TODOS:
        return JSONResponse({"error": "id already exists"}, status_code=409)
    item = {"id": todo_id, "title": title, "done": False}
    TODOS[todo_id] = item
    return JSONResponse(item, status_code=201)


@app.get("/api/todos")
def list_todos() -> list[dict[str, object]]:
    return list(TODOS.values())


@app.post("/api/todos/{todo_id}/complete")
def complete_todo(todo_id: str):
    item = TODOS.get(todo_id)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if PERSIST:
        item["done"] = True
    return JSONResponse({"id": todo_id, "ok": True}, status_code=200)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8472"))
    uvicorn.run(app, host="127.0.0.1", port=port)
