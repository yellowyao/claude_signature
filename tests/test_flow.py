import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import checker, db, main, runner
from app.catalog import cost_of


MODEL = "claude-opus-5-5"
USAGE = {"input_tokens": 100, "output_tokens": 10}
ASSISTANT = [
    {"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl"},
    {"type": "text", "text": "计算结果是 8，验证编号 TEST。"},
]


def message(content: list[dict], stop_reason: str = "end_turn") -> dict:
    return {"id": "msg_test", "model": MODEL, "content": content, "usage": USAGE, "stop_reason": stop_reason}


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.executescript(db.SCHEMA)
        self.addCleanup(connection.close)
        self.enterContext(patch.object(db, "_conn", connection))

    def create_task(self, stream: bool = False, rounds: int = 1) -> tuple[int, int]:
        key_id = db.insert("official_keys", {"name": "test", "api_key": "test", "created_at": db.now()})
        relay_id = db.insert("relays", {"name": "test", "base_url": "https://relay.invalid", "api_key": "test", "created_at": db.now(), "updated_at": db.now()})
        task_id = db.insert("tasks", {
            "created_at": db.now(), "status": "running", "official_key_id": key_id, "rounds": rounds,
            "stream_mode": "default", "models": [MODEL], "relay_ids": [relay_id],
        })
        record_id = db.insert("records", {
            "task_id": task_id, "relay_id": relay_id, "relay_name": "test", "relay_url": "https://relay.invalid",
            "model": MODEL, "relay_model": MODEL, "stream": int(stream), "status": "queued", "created_at": db.now(),
        })
        return task_id, record_id

    async def run_flow(self, reply, stream: bool = False, stop_reason: str = "end_turn", rounds: int = 1, replay_result: dict | None = None):
        task_id, record_id = self.create_task(stream, rounds)
        confirmation = reply if isinstance(reply, Exception) else (reply if isinstance(reply, dict) else message([{"type": "text", "text": reply}], stop_reason), "req_followup")
        call_relay = AsyncMock(side_effect=[(message(ASSISTANT), "req_mint"), confirmation] * rounds)
        replay = AsyncMock(return_value=replay_result if replay_result is not None else {"ok": True, "status": 200, "input_transformations": [], "usage": USAGE})
        official = SimpleNamespace(close=AsyncMock())
        relay = SimpleNamespace(close=AsyncMock())
        with patch.object(checker, "official_client", return_value=official), patch.object(checker, "relay_client", return_value=relay), patch.object(checker, "_call_relay", call_relay), patch.object(checker, "replay", replay):
            await runner._run_task(task_id)
        official.close.assert_awaited_once()
        relay.close.assert_awaited_once()
        self.assertEqual(db.one("SELECT status FROM tasks WHERE id = ?", (task_id,))["status"], "done")
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM controls")["n"], 0)
        record = db.one("SELECT * FROM records WHERE id = ?", (record_id,))
        stored = db.query("SELECT * FROM rounds WHERE record_id = ? ORDER BY idx", (record_id,))
        return record, stored, call_relay, replay

    async def test_yes_runs_only_replay_with_original_thinking(self):
        record, stored, call_relay, replay = await self.run_flow(" 是。 ", stream=True)
        self.assertEqual(record["verdict"], "pass")
        self.assertEqual(call_relay.await_count, 2)
        replay.assert_awaited_once()
        followup = call_relay.await_args_list[1].args[1]
        self.assertTrue(call_relay.await_args_list[1].args[2])
        self.assertEqual(followup["messages"][1]["content"], ASSISTANT)
        self.assertEqual(followup["messages"][2]["content"], checker.RELEVANCE_QUESTION)
        self.assertEqual(replay.await_args.args[2], stored[0]["mint"]["challenge"])
        self.assertEqual(replay.await_args.args[3], ASSISTANT)
        self.assertTrue(stored[0]["relevance"]["related"])
        self.assertEqual(stored[0]["relevance"]["answer"], "是。")
        self.assertEqual(record["cost_relay"], round(cost_of(MODEL, USAGE) * 2, 6))
        self.assertEqual(record["cost_official"], round(cost_of(MODEL, USAGE), 6))
        self.assertEqual(record["negative"], {})

    async def test_reasoning_extraction_refusal_runs_replay_and_preserves_followup(self):
        for stream in (False, True):
            for content in ([], [{"type": "text", "text": "我无法提供思考过程。"}]):
                with self.subTest(stream=stream, content=content):
                    response = message(content, "refusal")
                    response["stop_details"] = {"type": "refusal", "category": "reasoning_extraction"}
                    response["usage"] = {"input_tokens": 250, "output_tokens": 20}
                    record, stored, call_relay, replay = await self.run_flow(response, stream=stream)
                    self.assertEqual(record["verdict"], "pass")
                    self.assertEqual(call_relay.await_count, 2)
                    self.assertEqual([call.args[2] for call in call_relay.await_args_list], [stream, stream])
                    replay.assert_awaited_once()
                    self.assertEqual(replay.await_args.args[2], stored[0]["mint"]["challenge"])
                    self.assertEqual(replay.await_args.args[3], ASSISTANT)
                    relevance = stored[0]["relevance"]
                    # 拒绝仅放行官方校验，不能记录成模型已回答“是”。
                    self.assertTrue(relevance["ok"])
                    self.assertEqual(relevance["kind"], "reasoning_extraction_refusal")
                    self.assertIsNone(relevance["related"])
                    self.assertEqual(relevance["answer"], "" if not content else content[0]["text"])
                    self.assertEqual(relevance["response"], response)
                    self.assertEqual(relevance["usage"], response["usage"])
                    self.assertEqual(relevance["request_id"], "req_followup")
                    self.assertEqual(stored[0]["replay"]["verdict"], "pass")
                    self.assertEqual(record["cost_relay"], round(cost_of(MODEL, USAGE) + cost_of(MODEL, response["usage"]), 6))
                    self.assertEqual(record["cost_official"], round(cost_of(MODEL, USAGE), 6))

    async def test_reasoning_extraction_refusal_keeps_official_forged_verdict(self):
        response = message([], "refusal")
        response["stop_details"] = {"type": "refusal", "category": "reasoning_extraction"}
        replay_result = {"ok": False, "status": 400, "error": "Invalid signature in thinking block"}
        record, stored, call_relay, replay = await self.run_flow(response, replay_result=replay_result)
        replay.assert_awaited_once()
        self.assertEqual(call_relay.await_count, 2)
        self.assertEqual((record["verdict"], record["reason"]), ("forged", "forged"))
        self.assertEqual((stored[0]["verdict"], stored[0]["reason"]), ("forged", "forged"))
        self.assertEqual(stored[0]["replay"]["error"], replay_result["error"])
        self.assertEqual(stored[0]["relevance"]["kind"], "reasoning_extraction_refusal")

    async def test_other_refusals_and_invalid_metadata_never_call_official(self):
        response = message([{"type": "text", "text": "refusal reasoning_extraction"}], "refusal")
        responses = [response]
        responses.extend({**response, "stop_details": details} for details in (
            {"type": "refusal", "category": "other"},
            {"type": "other", "category": "reasoning_extraction"},
            {"type": "refusal"}, {}, None, [], "reasoning_extraction",
        ))
        for followup in responses:
            with self.subTest(stop_details=followup.get("stop_details", "missing")):
                record, stored, call_relay, replay = await self.run_flow(followup)
                replay.assert_not_awaited()
                self.assertEqual(call_relay.await_count, 2)
                self.assertEqual((record["verdict"], record["reason"]), ("undetectable", "relevance_unconfirmed"))
                self.assertFalse(stored[0]["relevance"]["ok"])
                self.assertEqual(stored[0]["relevance"]["response"], followup)
                self.assertEqual(stored[0]["replay"], {})
                self.assertEqual(record["cost_relay"], round(cost_of(MODEL, USAGE) * 2, 6))
                self.assertEqual(record["cost_official"], 0)

    async def test_reasoning_extraction_refusal_does_not_bypass_invalid_text(self):
        response = message([{"type": "text", "text": None}], "refusal")
        response["stop_details"] = {"type": "refusal", "category": "reasoning_extraction"}
        record, stored, _, replay = await self.run_flow(response)
        replay.assert_not_awaited()
        self.assertEqual((record["verdict"], record["reason"]), ("undetectable", "unsupported_format"))
        self.assertEqual(stored[0]["relevance"]["response"], response)
        self.assertEqual(stored[0]["relevance"]["usage"], USAGE)
        self.assertEqual(record["cost_relay"], round(cost_of(MODEL, USAGE) * 2, 6))
        self.assertEqual(record["cost_official"], 0)

    async def test_unconfirmed_replies_never_call_official(self):
        # “不是”包含“是”，不能用子串判断；被截断的“是”也不算完整确认。
        cases = [
            ("不是", "end_turn", "reused", "thinking_unrelated"),
            ("是，与题目有关", "end_turn", "undetectable", "relevance_unconfirmed"),
            ("是？", "end_turn", "undetectable", "relevance_unconfirmed"),
            ("", "end_turn", "undetectable", "relevance_unconfirmed"),
            ("是", "max_tokens", "undetectable", "relevance_unconfirmed"),
            (RuntimeError("relay failed"), "end_turn", "error", "relay_error"),
        ]
        for reply, stop_reason, verdict, reason in cases:
            with self.subTest(reply=reply, stop_reason=stop_reason):
                record, stored, call_relay, replay = await self.run_flow(reply, stop_reason=stop_reason)
                replay.assert_not_awaited()
                self.assertEqual(call_relay.await_count, 2)
                self.assertEqual((record["verdict"], record["reason"]), (verdict, reason))
                self.assertEqual(record["cost_official"], 0)
                self.assertFalse(stored[0]["relevance"]["ok"])
                self.assertEqual(stored[0]["replay"], {})

    async def test_each_round_gets_its_own_followup(self):
        record, stored, call_relay, replay = await self.run_flow("是", rounds=2)
        self.assertEqual(call_relay.await_count, 4)
        self.assertEqual(replay.await_count, 2)
        self.assertEqual([row["idx"] for row in stored], [0, 1])
        self.assertNotEqual(stored[0]["mint"]["challenge"], stored[1]["mint"]["challenge"])
        self.assertEqual(record["verdict"], "pass")

    async def test_invalid_followup_text_keeps_response_cost_and_later_rounds(self):
        record, stored, call_relay, replay = await self.run_flow(None, rounds=2)
        replay.assert_not_awaited()
        self.assertEqual(call_relay.await_count, 4)
        self.assertEqual(len(stored), 2)
        self.assertEqual(record["verdict"], "undetectable")
        self.assertEqual(record["cost_relay"], round(cost_of(MODEL, USAGE) * 4, 6))
        for row in stored:
            self.assertEqual(row["relevance"]["kind"], "unsupported_format")
            self.assertIsNone(row["relevance"]["response"]["content"][0]["text"])
            self.assertEqual(row["relevance"]["usage"], USAGE)
            self.assertEqual(row["replay"], {})

    async def test_followup_without_answer_text_or_effort(self):
        assistant = ASSISTANT[:1]
        mint_result = {"challenge": {"prompt": "question"}, "params": {}}
        with patch.object(checker, "_call_relay", AsyncMock(return_value=(message([{"type": "text", "text": "是"}]), None))) as call:
            result = await checker.check_relevance(None, MODEL, mint_result, assistant, False, checker.DEFAULT_SYSTEM)
        self.assertTrue(result["ok"])
        params = call.await_args.args[1]
        self.assertNotIn("output_config", params)
        self.assertNotIn("tools", params)
        self.assertNotIn("tool_choice", params)
        self.assertEqual(params["messages"][-1]["content"], checker.RELEVANCE_QUESTION)

    async def test_all_stages_use_normal_conversation_without_tools(self):
        call_relay = AsyncMock(side_effect=[
            (message(ASSISTANT), "req_mint"),
            (message([{"type": "text", "text": "是"}]), "req_followup"),
        ])
        raw = SimpleNamespace(status_code=200, headers={"request-id": "req_replay"}, json=AsyncMock(return_value=message([])))
        create = AsyncMock(return_value=raw)
        official = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(with_raw_response=SimpleNamespace(create=create))))
        with patch.object(checker, "_call_relay", call_relay):
            minted = await checker.mint(None, MODEL, False, checker.DEFAULT_SYSTEM)
            relevance = await checker.check_relevance(None, MODEL, minted, ASSISTANT, False, checker.DEFAULT_SYSTEM)
        replayed = await checker.replay(official, MODEL, minted["challenge"], ASSISTANT, checker.DEFAULT_SYSTEM)
        self.assertTrue(minted["ok"])
        self.assertTrue(relevance["ok"])
        self.assertTrue(replayed["ok"])
        requests = [call.args[1] for call in call_relay.await_args_list] + [create.await_args.kwargs]
        for params in requests:
            self.assertNotIn("tools", params)
            self.assertNotIn("tool_choice", params)
            for entry in params["messages"]:
                if isinstance(entry["content"], list):
                    self.assertFalse(any(block["type"] in ("tool_use", "tool_result") for block in entry["content"]))
        prompt = requests[0]["messages"][0]["content"]
        self.assertIn(minted["challenge"]["nonce"], prompt)
        self.assertNotIn("submit_answer", prompt)
        self.assertNotIn("submit_answer", str(checker.DEFAULT_SYSTEM))
        for params in requests[1:]:
            self.assertEqual(params["messages"][0], requests[0]["messages"][0])
            self.assertEqual(params["messages"][1], {"role": "assistant", "content": ASSISTANT})
            self.assertIsInstance(params["messages"][2]["content"], str)

    def test_unsolicited_tool_blocks_are_dropped_before_normal_followup(self):
        redacted = {"type": "redacted_thinking", "data": "c2lnbmVk"}
        unsolicited = {"type": "tool_use", "id": "tool_1", "name": "submit_answer", "input": {"answer": 8, "nonce": "TEST"}}
        # 丢弃意外工具调用时，保留两类思考签名、文本及原有顺序。
        sanitized = checker.sanitize_content([ASSISTANT[0], unsolicited, redacted, ASSISTANT[1]])
        self.assertEqual(sanitized, [ASSISTANT[0], redacted, ASSISTANT[1]])
        followup = checker.replay_messages({"prompt": "question"}, sanitized, checker.RELEVANCE_QUESTION)
        self.assertEqual(followup[1]["content"], sanitized)
        self.assertEqual(followup[2], {"role": "user", "content": checker.RELEVANCE_QUESTION})

    async def test_startup_migrates_only_exact_old_builtin_system(self):
        old_system = [{"type": "text", "text": "You are a precise calculator. Work the problem out carefully, then report the final result by calling the submit_answer tool."}]
        custom = [{"type": "text", "text": "Keep my custom instructions."}]
        old_with_metadata = [{**old_system[0], "cache_control": {"type": "ephemeral"}}]
        cases = [
            ("old_default", old_system, checker.DEFAULT_SYSTEM, True),
            ("absent", None, checker.DEFAULT_SYSTEM, False),
            ("custom", custom, custom, False),
            ("old_with_metadata", old_with_metadata, old_with_metadata, False),
        ]
        for label, saved, expected, migrated in cases:
            with self.subTest(system=label):
                db.execute("DELETE FROM settings WHERE key = ?", ("system",))
                if saved is not None:
                    db.set_setting("system", saved)
                # 启动迁移仅使用当前测试的内存数据库，不打开实际数据文件。
                with patch.object(db, "init") as initialize, patch.object(db, "set_setting", wraps=db.set_setting) as save:
                    async with main.lifespan(main.app):
                        self.assertEqual(main.get_settings()["system"], expected)
                    initialize.assert_called_once_with()
                    if migrated:
                        save.assert_called_once_with("system", checker.DEFAULT_SYSTEM)
                    else:
                        save.assert_not_called()
                self.assertEqual(db.get_setting("system", None), expected if saved is not None else None)


class MigrationTests(unittest.TestCase):
    def test_old_database_adds_empty_relevance_without_losing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signature.db"
            old_schema = db.SCHEMA.replace("    relevance TEXT NOT NULL DEFAULT '{}',\n", "")
            with sqlite3.connect(path) as connection:
                connection.executescript(old_schema)
                connection.execute("INSERT INTO rounds (record_id, idx, verdict, mint) VALUES (1, 0, 'pass', ?)", ('{"ok": true}',))
            with patch.object(db, "DATA_DIR", Path(directory)), patch.object(db, "DB_PATH", path), patch.object(db, "_conn", None):
                db.init()
                try:
                    row = db.one("SELECT * FROM rounds WHERE id = 1")
                    self.assertEqual(row["verdict"], "pass")
                    self.assertEqual(row["mint"], {"ok": True})
                    self.assertEqual(row["relevance"], {})
                finally:
                    db._conn.close()


if __name__ == "__main__":
    unittest.main()
