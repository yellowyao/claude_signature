"""FastAPI app: JSON API under /api, single-page UI under /."""

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import checker, db, runner
from .catalog import MODEL_IDS, MODELS

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    runner.recover_interrupted()
    yield


app = FastAPI(title="Claude 签名检测", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


def mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 12:
        return key[:2] + "…" + key[-2:]
    return key[:7] + "…" + key[-4:]


# ---------------------------------------------------------------- meta


@app.get("/api/meta")
def meta():
    return {"models": MODELS, "reasons": runner.REASONS}


@app.get("/api/settings")
def get_settings():
    return {"official_concurrency": db.get_setting("official_concurrency", 3)}


class SettingsIn(BaseModel):
    official_concurrency: int = Field(ge=1, le=20)


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    db.set_setting("official_concurrency", body.official_concurrency)
    return get_settings()


# ---------------------------------------------------------------- relays


class RelayIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=1)
    api_key: str = ""
    auth_mode: str = Field(default="auto", pattern="^(auto|x-api-key|bearer)$")
    model_map: dict[str, str] = {}
    stream: bool = False
    note: str = ""


def relay_out(r: dict) -> dict:
    return {**{k: v for k, v in r.items() if k != "api_key"}, "api_key_masked": mask(r["api_key"])}


def _clean_map(m: dict[str, str]) -> dict[str, str]:
    return {k: v.strip() for k, v in m.items() if k in MODEL_IDS and v.strip() and v.strip() != k}


@app.get("/api/relays")
def list_relays():
    return [relay_out(r) for r in db.query("SELECT * FROM relays WHERE deleted = 0 ORDER BY id")]


@app.post("/api/relays")
def create_relay(body: RelayIn):
    if not body.api_key.strip():
        raise HTTPException(400, "请填写中转站 Key")
    t = db.now()
    rid = db.insert("relays", {
        "name": body.name.strip(), "base_url": body.base_url.strip(), "api_key": body.api_key.strip(),
        "auth_mode": body.auth_mode, "model_map": _clean_map(body.model_map), "stream": int(body.stream),
        "note": body.note, "created_at": t, "updated_at": t,
    })
    return relay_out(db.one("SELECT * FROM relays WHERE id = ?", (rid,)))


def _get_relay(rid: int) -> dict:
    r = db.one("SELECT * FROM relays WHERE id = ? AND deleted = 0", (rid,))
    if not r:
        raise HTTPException(404, "中转站不存在")
    return r


@app.put("/api/relays/{rid}")
def update_relay(rid: int, body: RelayIn):
    _get_relay(rid)
    data = {
        "name": body.name.strip(), "base_url": body.base_url.strip(), "auth_mode": body.auth_mode,
        "model_map": _clean_map(body.model_map), "stream": int(body.stream), "note": body.note,
        "updated_at": db.now(),
    }
    if body.api_key.strip():
        data["api_key"] = body.api_key.strip()
    db.update("relays", rid, data)
    return relay_out(_get_relay(rid))


@app.delete("/api/relays/{rid}")
def delete_relay(rid: int):
    _get_relay(rid)
    # soft delete keeps history readable; the key itself is wiped
    db.update("relays", rid, {"deleted": 1, "api_key": "", "updated_at": db.now()})
    return {"ok": True}


class RelayTestIn(BaseModel):
    model: str | None = None


@app.post("/api/relays/{rid}/test")
async def test_relay(rid: int, body: RelayTestIn):
    relay = _get_relay(rid)
    client = checker.relay_client(relay)
    out: dict = {"base_url": checker.normalize_base_url(relay["base_url"])}
    try:
        try:
            page = await client.models.list(limit=100)
            out["models"] = {"ok": True, "ids": [m.id for m in page.data]}
        except Exception as e:  # noqa: BLE001
            out["models"] = {"ok": False, "error": checker._error_text(e)}
        if body.model:
            started = time.perf_counter()
            try:
                msg = await client.messages.create(
                    model=body.model, max_tokens=512,
                    messages=[{"role": "user", "content": "回复 OK 两个字母。"}],
                )
                text = "".join(b.text for b in msg.content if b.type == "text")
                out["message"] = {"ok": True, "text": text, "model": msg.model,
                                  "latency_ms": int((time.perf_counter() - started) * 1000)}
            except Exception as e:  # noqa: BLE001
                out["message"] = {"ok": False, "error": checker._error_text(e)}
    finally:
        await client.close()
    return out


# ---------------------------------------------------------------- official keys


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    api_key: str = ""
    is_default: bool = False
    note: str = ""


def key_out(k: dict) -> dict:
    return {**{x: v for x, v in k.items() if x != "api_key"}, "api_key_masked": mask(k["api_key"])}


def _set_default(kid: int) -> None:
    db.execute("UPDATE official_keys SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (kid,))


@app.get("/api/keys")
def list_keys():
    return [key_out(k) for k in db.query("SELECT * FROM official_keys ORDER BY id")]


@app.post("/api/keys")
def create_key(body: KeyIn):
    if not body.api_key.strip():
        raise HTTPException(400, "请填写官方 Key")
    first = db.one("SELECT COUNT(*) AS n FROM official_keys")["n"] == 0
    kid = db.insert("official_keys", {
        "name": body.name.strip(), "api_key": body.api_key.strip(), "note": body.note,
        "is_default": 0, "created_at": db.now(),
    })
    if body.is_default or first:
        _set_default(kid)
    return key_out(db.one("SELECT * FROM official_keys WHERE id = ?", (kid,)))


def _get_key(kid: int) -> dict:
    k = db.one("SELECT * FROM official_keys WHERE id = ?", (kid,))
    if not k:
        raise HTTPException(404, "官方 Key 不存在")
    return k


@app.put("/api/keys/{kid}")
def update_key(kid: int, body: KeyIn):
    _get_key(kid)
    data = {"name": body.name.strip(), "note": body.note}
    if body.api_key.strip():
        data["api_key"] = body.api_key.strip()
    db.update("official_keys", kid, data)
    if body.is_default:
        _set_default(kid)
    return key_out(_get_key(kid))


@app.delete("/api/keys/{kid}")
def delete_key(kid: int):
    k = _get_key(kid)
    db.execute("DELETE FROM official_keys WHERE id = ?", (kid,))
    if k["is_default"]:
        nxt = db.one("SELECT id FROM official_keys ORDER BY id LIMIT 1")
        if nxt:
            _set_default(nxt["id"])
    return {"ok": True}


@app.post("/api/keys/{kid}/test")
async def test_key(kid: int):
    k = _get_key(kid)
    client = checker.official_client(k["api_key"])
    try:
        page = await client.models.list(limit=100)
        ids = {m.id for m in page.data}
        return {"ok": True, "available": {mid: mid in ids for mid in MODEL_IDS}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": checker._error_text(e)}
    finally:
        await client.close()


# ---------------------------------------------------------------- tasks


class TaskIn(BaseModel):
    relay_ids: list[int] = Field(min_length=1)
    models: list[str] = Field(min_length=1)
    rounds: int = Field(default=1, ge=1, le=10)
    stream_mode: str = Field(default="default", pattern="^(default|stream|nonstream)$")
    official_key_id: int


@app.post("/api/tasks")
async def create_task(body: TaskIn):
    models = [m for m in MODEL_IDS if m in body.models]
    if not models:
        raise HTTPException(400, "请选择至少一个模型")
    key = _get_key(body.official_key_id)
    relays = [_get_relay(rid) for rid in dict.fromkeys(body.relay_ids)]
    tid = db.insert("tasks", {
        "created_at": db.now(), "status": "running", "official_key_id": key["id"],
        "official_key_name": key["name"], "rounds": body.rounds, "stream_mode": body.stream_mode,
        "models": models, "relay_ids": [r["id"] for r in relays],
    })
    for r in relays:
        stream = {"stream": True, "nonstream": False}.get(body.stream_mode, bool(r["stream"]))
        for m in models:
            db.insert("records", {
                "task_id": tid, "relay_id": r["id"], "relay_name": r["name"],
                "relay_url": checker.normalize_base_url(r["base_url"]), "model": m,
                "relay_model": r["model_map"].get(m, m), "stream": int(stream),
                "status": "queued", "created_at": db.now(),
            })
    runner.start(tid)
    return {"id": tid}


RECORD_LIST_COLS = (
    "r.id, r.task_id, r.relay_id, r.relay_name, r.relay_url, r.model, r.relay_model, r.stream, "
    "r.status, r.verdict, r.reason, r.cost_official, r.cost_relay, r.created_at, r.finished_at, "
    "COALESCE(rl.deleted, 1) AS relay_deleted"
)


@app.get("/api/tasks")
def list_tasks(limit: int = 50):
    tasks = db.query("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
    for t in tasks:
        t["counts"] = {r["verdict"] or "running": r["n"] for r in db.query(
            "SELECT verdict, COUNT(*) AS n FROM records WHERE task_id = ? GROUP BY verdict", (t["id"],))}
    return tasks


@app.get("/api/tasks/{tid}")
def get_task(tid: int):
    t = db.one("SELECT * FROM tasks WHERE id = ?", (tid,))
    if not t:
        raise HTTPException(404, "任务不存在")
    t["controls"] = db.query("SELECT * FROM controls WHERE task_id = ? ORDER BY id", (tid,))
    t["records"] = db.query(
        f"SELECT {RECORD_LIST_COLS} FROM records r LEFT JOIN relays rl ON rl.id = r.relay_id "
        "WHERE r.task_id = ? ORDER BY r.id", (tid,))
    return t


@app.delete("/api/tasks/{tid}")
def delete_task(tid: int):
    t = db.one("SELECT status FROM tasks WHERE id = ?", (tid,))
    if not t:
        raise HTTPException(404, "任务不存在")
    if t["status"] == "running":
        raise HTTPException(400, "任务仍在运行，结束后才能删除")
    db.execute("DELETE FROM tasks WHERE id = ?", (tid,))
    return {"ok": True}


# ---------------------------------------------------------------- records


@app.get("/api/records")
def list_records(relay_id: int | None = None, model: str | None = None, verdict: str | None = None,
                 limit: int = 50, offset: int = 0):
    where, params = ["r.status = 'done'"], []
    if relay_id:
        where.append("r.relay_id = ?")
        params.append(relay_id)
    if model:
        where.append("r.model = ?")
        params.append(model)
    if verdict:
        where.append("r.verdict = ?")
        params.append(verdict)
    w = " AND ".join(where)
    total = db.one(f"SELECT COUNT(*) AS n FROM records r WHERE {w}", params)["n"]
    rows = db.query(
        f"SELECT {RECORD_LIST_COLS} FROM records r LEFT JOIN relays rl ON rl.id = r.relay_id "
        f"WHERE {w} ORDER BY r.id DESC LIMIT ? OFFSET ?", [*params, limit, offset])
    return {"total": total, "items": rows}


def _record_detail(rec_id: int) -> dict:
    rec = db.one(
        f"SELECT r.*, COALESCE(rl.deleted, 1) AS relay_deleted FROM records r "
        "LEFT JOIN relays rl ON rl.id = r.relay_id WHERE r.id = ?", (rec_id,))
    if not rec:
        raise HTTPException(404, "记录不存在")
    rec["rounds"] = db.query("SELECT * FROM rounds WHERE record_id = ? ORDER BY idx", (rec_id,))
    rec["positive"] = db.one("SELECT * FROM controls WHERE task_id = ? AND model = ?", (rec["task_id"], rec["model"]))
    rec["task"] = db.one("SELECT id, created_at, official_key_name, rounds, stream_mode FROM tasks WHERE id = ?",
                         (rec["task_id"],))
    return rec


@app.get("/api/records/{rec_id}")
def get_record(rec_id: int):
    return _record_detail(rec_id)


@app.get("/api/records/{rec_id}/export")
def export_record(rec_id: int):
    rec = _record_detail(rec_id)
    body = json.dumps(rec, ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="signature-record-{rec_id}.json"'})


@app.delete("/api/records/{rec_id}")
def delete_record(rec_id: int):
    rec = db.one("SELECT status FROM records WHERE id = ?", (rec_id,))
    if not rec:
        raise HTTPException(404, "记录不存在")
    if rec["status"] != "done":
        raise HTTPException(400, "检测仍在进行，结束后才能删除")
    db.execute("DELETE FROM records WHERE id = ?", (rec_id,))
    return {"ok": True}


# ---------------------------------------------------------------- overview


@app.get("/api/overview")
def overview():
    relays = db.query("SELECT * FROM relays WHERE deleted = 0 ORDER BY id")
    cards = []
    for r in relays:
        latest = db.query(
            "SELECT model, verdict, reason, id, finished_at FROM records WHERE id IN ("
            " SELECT MAX(id) FROM records WHERE relay_id = ? AND status = 'done' GROUP BY model)", (r["id"],))
        stats = db.one(
            "SELECT COUNT(*) AS total, SUM(verdict = 'pass') AS pass, SUM(verdict = 'forged') AS forged, "
            "SUM(verdict = 'suspicious') AS suspicious, SUM(verdict IN ('pass','forged','suspicious')) AS decided, "
            "MAX(finished_at) AS last_at, SUM(cost_official) AS cost_official, SUM(cost_relay) AS cost_relay "
            "FROM records WHERE relay_id = ? AND status = 'done'", (r["id"],))
        cards.append({"relay": relay_out(r), "latest": {x["model"]: x for x in latest}, "stats": stats})
    totals = db.one(
        "SELECT COUNT(*) AS records, SUM(verdict = 'forged') AS forged, SUM(verdict = 'suspicious') AS suspicious, "
        "SUM(cost_official) AS cost_official, SUM(cost_relay) AS cost_relay FROM records WHERE status = 'done'")
    control_cost = db.one("SELECT SUM(cost_official) AS c FROM controls")["c"] or 0
    totals["cost_official"] = (totals["cost_official"] or 0) + control_cost
    totals["tasks"] = db.one("SELECT COUNT(*) AS n FROM tasks")["n"]
    totals["relays"] = len(relays)
    totals["running"] = db.one("SELECT COUNT(*) AS n FROM tasks WHERE status = 'running'")["n"]
    return {"cards": cards, "totals": totals}
