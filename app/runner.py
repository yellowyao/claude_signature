"""Run relay generation and relevance checks, then official replay for confirmed rounds."""

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
    official = checker.official_client(key["api_key"], key["id"], task_id)
    official_sem = asyncio.Semaphore(int(db.get_setting("official_concurrency", 3)))
    system = db.get_setting("system", checker.DEFAULT_SYSTEM)
    relay_sems: dict[int, asyncio.Semaphore] = {}

    try:
        records = db.query("SELECT * FROM records WHERE task_id = ? ORDER BY id", (task_id,))
        cells = []
        for rec in records:
            relay = db.one("SELECT * FROM relays WHERE id = ?", (rec["relay_id"],))
            sem = relay_sems.setdefault(rec["relay_id"], asyncio.Semaphore(RELAY_CONCURRENCY))
            cells.append(_run_cell(rec, relay, task["rounds"], official, official_sem, sem, system))
        await asyncio.gather(*cells, return_exceptions=True)
        db.update("tasks", task_id, {"status": "done", "finished_at": db.now()})
    except Exception:  # noqa: BLE001
        log.exception("task %s crashed", task_id)
        db.update("tasks", task_id, {"status": "interrupted", "finished_at": db.now()})
    finally:
        await official.close()


async def _run_cell(rec, relay, rounds, official, official_sem, relay_sem, system: list[dict]) -> None:
    rid = rec["id"]
    model = rec["model"]
    cost_relay = cost_official = 0.0
    verdicts: list[tuple[str, str]] = []
    client = checker.relay_client(relay)
    try:
        for i in range(rounds):
            db.update("records", rid, {"status": "minting"})
            async with relay_sem:
                m = await checker.mint(client, rec["relay_model"], bool(rec["stream"]), system)
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
            db.update("records", rid, {"status": "confirming", "cost_relay": cost_relay})
            async with relay_sem:
                relevance = await checker.check_relevance(client, rec["relay_model"], m, assistant, bool(rec["stream"]), system)
            cost_relay += cost_of(model, relevance.get("usage"))
            if not relevance["ok"]:
                reason = relevance["kind"]
                v = "reused" if reason == "thinking_unrelated" else "error" if reason == "relay_error" else "undetectable"
                verdicts.append((v, reason))
                db.insert("rounds", {
                    "record_id": rid, "idx": i, "verdict": v, "reason": reason,
                    "mint": _mint_summary(m), "relevance": relevance, "replay": {},
                    "heuristics": checker.heuristics(m, rec["relay_model"]),
                })
                db.update("records", rid, {"cost_relay": cost_relay})
                continue

            db.update("records", rid, {"status": "replaying", "cost_relay": cost_relay})
            async with official_sem:
                with checker.official_request_context("replay", model, rid, i):
                    rep = await checker.replay(official, model, m["challenge"], assistant, system)
            cost_official += cost_of(model, rep.get("usage"))
            v, reason = checker.classify_replay(rep, checker.thinking_paths(assistant))
            verdicts.append((v, reason))
            db.insert("rounds", {
                "record_id": rid, "idx": i, "verdict": v, "reason": reason,
                "mint": _mint_summary(m), "relevance": relevance, "replay": _replay_summary(rep, v, reason),
                "heuristics": checker.heuristics(m, rec["relay_model"]),
            })
            db.update("records", rid, {"cost_official": cost_official})

        verdict, reason = _aggregate(verdicts)
        db.update("records", rid, {
            "status": "done", "verdict": verdict, "reason": reason,
            "cost_official": round(cost_official, 6), "cost_relay": round(cost_relay, 6), "finished_at": db.now(),
        })
    except Exception as e:  # noqa: BLE001
        log.exception("record %s crashed", rid)
        db.update("records", rid, {
            "status": "done", "verdict": "error", "reason": "relay_error",
            "cost_official": round(cost_official, 6), "cost_relay": round(cost_relay, 6), "finished_at": db.now(),
        })
    finally:
        await client.close()


SEVERITY = ["forged", "reused", "suspicious", "pass", "undetectable", "error"]


def _aggregate(verdicts: list[tuple[str, str]]) -> tuple[str, str]:
    verdict, reason = "error", "relay_error"
    for level in SEVERITY:
        hit = next((r for v, r in verdicts if v == level), None)
        if hit:
            verdict, reason = level, hit
            break
    return verdict, reason
