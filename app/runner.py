"""Runs a check task: one positive control per model, then every relay x model cell."""

import asyncio
import logging

from . import checker, db
from .catalog import cost_of

log = logging.getLogger("runner")

RELAY_CONCURRENCY = 2
EXTRA_REASONS = {
    "positive_failed": "阳性对照失败（官方铸造→官方回放未通过），本次结论不可信",
    "negative_failed": "阴性对照失败（篡改后的签名没有被官方拒绝），本次结论不可信",
    "interrupted": "服务重启，检测被中断",
}
REASONS = {**checker.REASONS, **EXTRA_REASONS}

_running: dict[int, asyncio.Task] = {}


def recover_interrupted() -> None:
    """Called at startup: anything left running belonged to a previous process."""
    db.execute("UPDATE tasks SET status = 'interrupted', finished_at = ? WHERE status = 'running'", (db.now(),))
    db.execute(
        "UPDATE records SET status = 'done', verdict = 'error', reason = 'interrupted', finished_at = ? "
        "WHERE status != 'done'",
        (db.now(),),
    )
    db.execute("UPDATE controls SET status = 'done', ok = 0, reason = 'interrupted' WHERE status != 'done'")


def start(task_id: int) -> None:
    _running[task_id] = asyncio.create_task(_run_task(task_id))
    _running[task_id].add_done_callback(lambda _t: _running.pop(task_id, None))


def _mint_summary(m: dict) -> dict:
    return {
        "ok": m.get("ok"),
        "kind": m.get("kind"),
        "error": m.get("error"),
        "status": m.get("status"),
        "attempts": m.get("attempts"),
        "latency_ms": m.get("latency_ms"),
        "request_id": m.get("request_id"),
        "challenge": m.get("challenge"),
        "params": m.get("params"),
        "response": m.get("raw"),
    }


def _replay_summary(rep: dict, verdict: str, reason: str) -> dict:
    return {**rep, "verdict": verdict, "reason": reason}


async def _run_task(task_id: int) -> None:
    task = db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    key = db.one("SELECT * FROM official_keys WHERE id = ?", (task["official_key_id"],))
    official = checker.official_client(key["api_key"])
    official_sem = asyncio.Semaphore(int(db.get_setting("official_concurrency", 3)))
    relay_sems: dict[int, asyncio.Semaphore] = {}

    try:
        controls = {
            model: asyncio.create_task(_positive_control(task_id, model, official, official_sem))
            for model in task["models"]
        }
        records = db.query("SELECT * FROM records WHERE task_id = ? ORDER BY id", (task_id,))
        cells = []
        for rec in records:
            relay = db.one("SELECT * FROM relays WHERE id = ?", (rec["relay_id"],))
            sem = relay_sems.setdefault(rec["relay_id"], asyncio.Semaphore(RELAY_CONCURRENCY))
            cells.append(_run_cell(rec, relay, task["rounds"], official, official_sem, sem, controls[rec["model"]]))
        await asyncio.gather(*cells, return_exceptions=True)
        await asyncio.gather(*controls.values(), return_exceptions=True)
        db.update("tasks", task_id, {"status": "done", "finished_at": db.now()})
    except Exception:  # noqa: BLE001
        log.exception("task %s crashed", task_id)
        db.update("tasks", task_id, {"status": "interrupted", "finished_at": db.now()})
    finally:
        await official.close()


async def _positive_control(task_id: int, model: str, official, sem) -> bool:
    cid = db.insert("controls", {"task_id": task_id, "model": model, "status": "running"})
    try:
        return await _positive_control_inner(cid, model, official, sem)
    except Exception as e:  # noqa: BLE001
        log.exception("positive control %s crashed", cid)
        db.update("controls", cid, {"status": "done", "ok": 0, "reason": "official_error", "detail": {"error": str(e)}})
        return False


async def _positive_control_inner(cid: int, model: str, official, sem) -> bool:
    cost = 0.0
    async with sem:
        m = await checker.mint(official, model, stream=False)
    cost += sum(cost_of(model, u) for u in m.get("usages", []))
    if not m["ok"]:
        db.update("controls", cid, {
            "status": "done", "ok": 0, "reason": m["kind"], "cost_official": cost,
            "detail": {"mint": _mint_summary(m)},
        })
        return False
    assistant = checker.sanitize_content(m["raw"]["content"])
    async with sem:
        rep = await checker.replay(official, model, m["challenge"], assistant)
    cost += cost_of(model, rep.get("usage"))
    verdict, reason = checker.classify_replay(rep, checker.thinking_paths(assistant))
    ok = verdict == "pass"
    db.update("controls", cid, {
        "status": "done", "ok": int(ok), "reason": reason, "cost_official": cost,
        "detail": {"mint": _mint_summary(m), "replay": _replay_summary(rep, verdict, reason)},
    })
    return ok


async def _run_cell(rec, relay, rounds, official, official_sem, relay_sem, control_fut) -> None:
    rid = rec["id"]
    model = rec["model"]
    cost_relay = cost_official = 0.0
    verdicts: list[tuple[str, str]] = []
    first_ok: tuple[dict, list] | None = None
    client = checker.relay_client(relay)
    try:
        for i in range(rounds):
            db.update("records", rid, {"status": "minting"})
            async with relay_sem:
                m = await checker.mint(client, rec["relay_model"], bool(rec["stream"]))
            cost_relay += sum(cost_of(model, u) for u in m.get("usages", []))
            if not m["ok"]:
                v = "error" if m["kind"] == "relay_error" else "undetectable"
                verdicts.append((v, m["kind"]))
                db.insert("rounds", {
                    "record_id": rid, "idx": i, "verdict": v, "reason": m["kind"],
                    "mint": _mint_summary(m), "replay": {},
                    "heuristics": checker.heuristics(m, rec["relay_model"]) if m.get("raw") else {},
                })
                db.update("records", rid, {"cost_relay": cost_relay})
                continue

            assistant = checker.sanitize_content(m["raw"]["content"])
            db.update("records", rid, {"status": "replaying", "cost_relay": cost_relay})
            async with official_sem:
                rep = await checker.replay(official, model, m["challenge"], assistant)
            cost_official += cost_of(model, rep.get("usage"))
            v, reason = checker.classify_replay(rep, checker.thinking_paths(assistant))
            verdicts.append((v, reason))
            first_ok = first_ok or (m["challenge"], assistant)
            db.insert("rounds", {
                "record_id": rid, "idx": i, "verdict": v, "reason": reason,
                "mint": _mint_summary(m), "replay": _replay_summary(rep, v, reason),
                "heuristics": checker.heuristics(m, rec["relay_model"]),
            })
            db.update("records", rid, {"cost_official": cost_official})

        negative = {}
        if first_ok:
            db.update("records", rid, {"status": "control"})
            challenge, assistant = first_ok
            async with official_sem:
                rep = await checker.replay(official, model, challenge, checker.tamper(assistant))
            cost_official += cost_of(model, rep.get("usage"))
            v, reason = checker.classify_replay(rep, checker.thinking_paths(assistant))
            negative = {**_replay_summary(rep, v, reason), "ok": v == "forged"}  # ok = control passed

        positive_ok = await control_fut
        verdict, reason = _aggregate(verdicts, positive_ok, negative)
        db.update("records", rid, {
            "status": "done", "verdict": verdict, "reason": reason, "negative": negative,
            "cost_official": round(cost_official, 6), "cost_relay": round(cost_relay, 6), "finished_at": db.now(),
        })
    except Exception as e:  # noqa: BLE001
        log.exception("record %s crashed", rid)
        db.update("records", rid, {
            "status": "done", "verdict": "error", "reason": "relay_error",
            "negative": {"error": str(e)}, "finished_at": db.now(),
        })
    finally:
        await client.close()


SEVERITY = ["forged", "suspicious", "pass", "undetectable", "error"]


def _aggregate(verdicts: list[tuple[str, str]], positive_ok: bool, negative: dict) -> tuple[str, str]:
    verdict, reason = "error", "relay_error"
    for level in SEVERITY:
        hit = next((r for v, r in verdicts if v == level), None)
        if hit:
            verdict, reason = level, hit
            break
    if verdict in ("forged", "suspicious", "pass"):
        if not positive_ok:
            return "invalid", "positive_failed"
        if not negative.get("ok"):
            return "invalid", "negative_failed"
    return verdict, reason
