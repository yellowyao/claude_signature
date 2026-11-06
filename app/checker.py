"""Mint a thinking block, ask the relay about relevance, then replay it to the official API.

Mint: ask the model a small reasoning puzzle with one tool available, so the reply is
`thinking + tool_use`. Replay: send [user, assistant(as returned), user(tool_result)] to the
official API with the same system/tools/first message (the signature is bound to that prefix),
plus the thinking-binding-controls beta so the response reports dropped blocks and why.
"""

import base64
import random
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar

import anthropic
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from . import db

OFFICIAL_BASE_URL = "https://api.anthropic.com"
BINDING_BETA = "thinking-binding-controls-2026-08-01"
MINT_MAX_TOKENS = 8000
RELEVANCE_MAX_TOKENS = 1024
REPLAY_MAX_TOKENS = 1024
MINT_ATTEMPTS = 3
RELEVANCE_QUESTION = "刚才的思考是否与题目有关？只回答“是”或“不是”，不要解释，也不要调用工具。"

DEFAULT_SYSTEM = [
    {
        "type": "text",
        "text": (
            "You are a precise calculator. Work the problem out carefully, "
            "then report the final result by calling the submit_answer tool."
        ),
    }
]

TOOLS = [
    {
        "name": "submit_answer",
        "description": "Submit the final integer answer together with the verification nonce.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "integer", "description": "The final integer result."},
                "nonce": {"type": "string", "description": "The verification nonce, copied verbatim."},
            },
            "required": ["answer", "nonce"],
            "additionalProperties": False,
        },
    }
]

THINKING_TYPES = ("thinking", "redacted_thinking")


def normalize_base_url(url: str) -> str:
    """The SDK appends /v1/messages itself; accept URLs pasted with or without it."""
    url = url.strip().rstrip("/")
    for suffix in ("/v1/messages", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def relay_client(relay: dict) -> AsyncAnthropic:
    key = relay["api_key"]
    base_url = normalize_base_url(relay["base_url"])
    common = dict(base_url=base_url, timeout=300.0, max_retries=1)
    mode = relay.get("auth_mode") or "auto"
    if mode == "bearer":
        return AsyncAnthropic(auth_token=key, **common)
    if mode == "x-api-key":
        return AsyncAnthropic(api_key=key, **common)
    # auto: send both headers, relays accept one or the other
    return AsyncAnthropic(api_key=key, default_headers={"Authorization": f"Bearer {key}"}, **common)


_official_request_context: ContextVar[dict] = ContextVar("official_request_context", default={})


@contextmanager
def official_request_context(stage: str, model: str, record_id: int | None = None, round_idx: int | None = None):
    # 官方客户端由并发检测共享，使用协程上下文防止日志串到其他记录。
    token = _official_request_context.set({"stage": stage, "model": model, "record_id": record_id, "round_idx": round_idx})
    try:
        yield
    finally:
        _official_request_context.reset(token)


def official_client(api_key: str, official_key_id: int, task_id: int | None = None) -> AsyncAnthropic:
    async def save_request(request) -> None:
        # 在发送前保存 SDK 序列化后的完整请求体，失败和自动重试也会逐次记录。
        body = await request.aread()
        request.extensions["official_request_id"] = db.insert("official_requests", {
            "created_at": db.now(), "official_key_id": official_key_id, "task_id": task_id,
            "method": request.method, "url": str(request.url), "request_body": body.decode("utf-8"),
            **_official_request_context.get(),
        })

    async def save_response(response) -> None:
        row_id = response.request.extensions["official_request_id"]
        db.update("official_requests", row_id, {
            "status_code": response.status_code, "response_request_id": response.headers.get("request-id"),
        })
        # 在 SDK 解析或因错误状态重试前读取，保留非 JSON 错误页等完整响应。
        await response.aread()
        db.update("official_requests", row_id, {"response_body": response.text})

    return AsyncAnthropic(
        api_key=api_key, base_url=OFFICIAL_BASE_URL, timeout=300.0, max_retries=2,
        http_client=DefaultAsyncHttpxClient(event_hooks={"request": [save_request], "response": [save_response]}),
    )


# ---------------------------------------------------------------- challenge


def new_challenge() -> dict:
    a = random.randint(101, 999)
    b = random.randint(101, 999)
    m = random.choice([97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157, 163])
    nonce = secrets.token_hex(4).upper()
    prompt = (
        f"验证编号 {nonce}。请计算 ({a}^3 + {b}^2) mod {m} 的值。"
        f"仔细计算后调用 submit_answer 工具提交：answer 为整数结果，nonce 为验证编号原样。"
    )
    return {"nonce": nonce, "prompt": prompt, "expected": (a**3 + b**2) % m}


def first_messages(challenge: dict) -> list[dict]:
    return [{"role": "user", "content": challenge["prompt"]}]


# ---------------------------------------------------------------- mint


def _error_text(e: Exception) -> str:
    if isinstance(e, anthropic.APIStatusError):
        body = e.body
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
        return e.message or str(e)
    return f"{type(e).__name__}: {e}"


def _status_of(e: Exception) -> int | None:
    return e.status_code if isinstance(e, anthropic.APIStatusError) else None


def _request_id_of(e: Exception) -> str | None:
    if isinstance(e, anthropic.APIStatusError):
        return e.response.headers.get("request-id")
    return None


async def _call_relay(client: AsyncAnthropic, params: dict, stream: bool) -> tuple[dict, str | None]:
    if stream:
        async with client.messages.stream(**params) as s:
            msg = await s.get_final_message()
        return msg.to_dict(), getattr(msg, "_request_id", None)
    raw = await client.messages.with_raw_response.create(**params)
    try:
        data = await raw.json()
    except ValueError:
        text = (await raw.text())[:500]
        raise FormatError(f"响应不是 JSON：{text}")
    return data, raw.headers.get("request-id")


class FormatError(Exception):
    pass


def _format_problem(data) -> str | None:
    if not isinstance(data, dict):
        return "响应不是 JSON 对象"
    if "choices" in data:
        return "返回的是 OpenAI 格式，不是 Anthropic 原生 /v1/messages 格式"
    if data.get("type") == "error":
        return None  # handled as relay error
    if not isinstance(data.get("content"), list):
        return "响应缺少 content 数组，不是 Anthropic 原生格式"
    return None


async def mint(client: AsyncAnthropic, model: str, stream: bool, system: list[dict]) -> dict:
    """Mint a signed thinking block. Retries a few times when the model answers without thinking."""
    result: dict = {"attempts": 0, "usages": []}
    use_effort = True
    for _ in range(MINT_ATTEMPTS):
        challenge = new_challenge()
        params = dict(
            model=model,
            max_tokens=MINT_MAX_TOKENS,
            system=system,
            tools=TOOLS,
            tool_choice={"type": "auto"},
            thinking={"type": "adaptive"},
            messages=first_messages(challenge),
        )
        if use_effort:
            params["output_config"] = {"effort": "high"}
        result["attempts"] += 1
        started = time.perf_counter()
        try:
            data, request_id = await _call_relay(client, params, stream)
        except FormatError as e:
            return {**result, "ok": False, "kind": "unsupported_format", "error": str(e)}
        except Exception as e:  # noqa: BLE001 - every relay failure is reported, never raised
            msg = _error_text(e)
            if stream and not isinstance(e, (anthropic.APIStatusError, anthropic.APIConnectionError)):
                msg = f"流式响应解析失败（中转站可能不支持流式）：{msg}"
            if use_effort and _status_of(e) == 400 and ("output_config" in msg or "effort" in msg):
                use_effort = False  # relay rejects the effort parameter: retry without it
                continue
            return {
                **result,
                "ok": False,
                "kind": "relay_error",
                "status": _status_of(e),
                "error": msg,
                "request_id": _request_id_of(e),
            }
        latency_ms = int((time.perf_counter() - started) * 1000)
        if isinstance(data, dict) and data.get("type") == "error":
            err = data.get("error") or {}
            return {**result, "ok": False, "kind": "relay_error", "status": 200,
                    "error": str(err.get("message") or err), "raw": data}
        problem = _format_problem(data)
        if problem:
            return {**result, "ok": False, "kind": "unsupported_format", "error": problem, "raw": data}

        result["usages"].append(data.get("usage") or {})
        blocks = [b for b in data["content"] if isinstance(b, dict) and b.get("type") in THINKING_TYPES]
        result.update(challenge=challenge, raw=data, latency_ms=latency_ms, request_id=request_id,
                      params={k: v for k, v in params.items() if k not in ("system", "tools", "messages")})
        if not blocks:
            continue  # adaptive thinking skipped this time; try a fresh challenge
        signed = [b for b in blocks if b.get("signature") or b.get("data")]
        if not signed:
            return {**result, "ok": False, "kind": "no_signature",
                    "error": "返回了 thinking 块，但没有 signature（中转站可能伪造或剥离了签名）"}
        return {**result, "ok": True}

    if "raw" in result:
        return {**result, "ok": False, "kind": "no_thinking",
                "error": f"连续 {result['attempts']} 次都没有返回 thinking 块"}
    return {**result, "ok": False, "kind": "relay_error", "error": "中转站拒绝了请求参数"}


# ---------------------------------------------------------------- replay


def sanitize_content(content: list) -> list[dict]:
    """Rebuild the assistant turn from known fields only; relays sometimes add extra keys."""
    out = []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "thinking":
            out.append({"type": "thinking", "thinking": b.get("thinking") or "", "signature": b.get("signature") or ""})
        elif t == "redacted_thinking":
            out.append({"type": "redacted_thinking", "data": b.get("data") or ""})
        elif t == "text":
            if b.get("text"):
                out.append({"type": "text", "text": b["text"]})
        elif t == "tool_use":
            out.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b.get("input") or {}})
    return out


def thinking_paths(assistant: list[dict]) -> list[str]:
    return [f"messages.1.content.{i}" for i, b in enumerate(assistant) if b["type"] in THINKING_TYPES]


def replay_messages(challenge: dict, assistant: list[dict], question: str | None = None) -> list[dict]:
    tool_ids = [b["id"] for b in assistant if b["type"] == "tool_use"]
    if tool_ids:
        follow = [{"type": "tool_result", "tool_use_id": tid, "content": "已收到。"} for tid in tool_ids]
        if question:
            # 工具结果必须放在前面，随后才能追加本轮追问。
            follow.append({"type": "text", "text": question})
    else:
        follow = question or "已收到，请用一句话确认结果。"
    return [*first_messages(challenge), {"role": "assistant", "content": assistant}, {"role": "user", "content": follow}]


async def check_relevance(client: AsyncAnthropic, model: str, mint_result: dict, assistant: list[dict], stream: bool, system: list[dict]) -> dict:
    params = dict(
        model=model,
        max_tokens=RELEVANCE_MAX_TOKENS,
        system=system,
        tools=TOOLS,
        tool_choice={"type": "none"},
        thinking={"type": "adaptive"},
        messages=replay_messages(mint_result["challenge"], assistant, RELEVANCE_QUESTION),
    )
    if "output_config" in mint_result["params"]:
        params["output_config"] = {"effort": "low"}
    result = {"question": RELEVANCE_QUESTION,
              "params": {k: v for k, v in params.items() if k not in ("system", "tools", "messages")}}
    started = time.perf_counter()
    try:
        data, request_id = await _call_relay(client, params, stream)
    except Exception as e:  # noqa: BLE001
        return {**result, "ok": False, "kind": "unsupported_format" if isinstance(e, FormatError) else "relay_error",
                "status": _status_of(e), "error": _error_text(e), "request_id": _request_id_of(e),
                "latency_ms": int((time.perf_counter() - started) * 1000)}

    result.update(response=data, request_id=request_id, status=200,
                  latency_ms=int((time.perf_counter() - started) * 1000))
    if isinstance(data, dict) and data.get("type") == "error":
        err = data.get("error") or {}
        return {**result, "ok": False, "kind": "relay_error", "error": str(err.get("message") or err)}
    problem = _format_problem(data)
    if problem:
        return {**result, "ok": False, "kind": "unsupported_format", "error": problem}

    result["usage"] = data.get("usage") or {}
    text_blocks = [b for b in data["content"] if isinstance(b, dict) and b.get("type") == "text"]
    if any(not isinstance(b.get("text"), str) for b in text_blocks):
        return {**result, "ok": False, "kind": "unsupported_format", "error": "相关性追问的 text 块缺少有效文本"}
    answer = "".join(b["text"] for b in text_blocks).strip()
    normalized = answer.strip(" \t\r\n。.!！\"'“”‘’")
    # 必须完整回答指定选项，不能把“不是”或截断的“是”误判为确认。
    related = normalized == "是" if normalized in ("是", "不是") and data.get("stop_reason") == "end_turn" else None
    kind = "relevance_confirmed" if related is True else "thinking_unrelated" if related is False else "relevance_unconfirmed"
    return {**result, "ok": related is True, "kind": kind, "related": related, "answer": answer}


async def replay(client: AsyncAnthropic, model: str, challenge: dict, assistant: list[dict], system: list[dict]) -> dict:
    params = dict(
        model=model,
        max_tokens=REPLAY_MAX_TOKENS,
        system=system,
        tools=TOOLS,
        tool_choice={"type": "auto"},
        thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
        output_config={"effort": "low"},
        messages=replay_messages(challenge, assistant),
        betas=[BINDING_BETA],
    )
    started = time.perf_counter()
    try:
        raw = await client.beta.messages.with_raw_response.create(**params)
        data = await raw.json()
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "status": _status_of(e),
            "error": _error_text(e),
            "request_id": _request_id_of(e),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": True,
        "status": raw.status_code,
        "request_id": raw.headers.get("request-id"),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "input_transformations": data.get("input_transformations"),
        "usage": data.get("usage") or {},
        "stop_reason": data.get("stop_reason"),
        "model": data.get("model"),
    }


REASONS = {
    "verified": "官方成功解密并校验签名，模型与上下文一致",
    "org_binding": "签名真实（官方可解密），来自其他账号；该模型有账号绑定，属正常",
    "no_diagnostics": "官方未拒绝签名，但响应里没有诊断字段，无法进一步核对模型与上下文",
    "forged": "官方拒绝了签名：签名是伪造或被篡改的",
    "model_mismatch": "签名真实，但不是声称的模型生成的，判为掺假（模型替换/降级）",
    "prefix_mismatch": "签名真实，但中转站改动了上下文（如注入 system prompt，常见于订阅号反代）",
    "unknown_transformation": "官方丢弃了该 thinking 块，原因未知",
    "replay_error": "官方回放请求报错（非签名问题）",
    "official_error": "官方 API 调用失败",
    "relay_error": "中转站请求失败",
    "unsupported_format": "中转站不支持 Anthropic 原生 /v1/messages 格式",
    "no_thinking": "中转站没有返回 thinking 块",
    "no_signature": "thinking 块没有 signature",
    "thinking_unrelated": "中转站回答“不是”，按检测规则判为签名复用，已跳过官方回放",
    "relevance_unconfirmed": "中转站未完整、明确地回答“是”或“不是”，已跳过官方回放",
}


def classify_replay(rep: dict, paths: list[str]) -> tuple[str, str]:
    """Return (verdict, reason_code). Verdicts: pass / forged / suspicious / error."""
    if not rep["ok"]:
        msg = (rep.get("error") or "").lower()
        if rep.get("status") == 400 and "signature" in msg and "thinking" in msg:
            if "different conversation" in msg:
                return "suspicious", "prefix_mismatch"
            return "forged", "forged"
        if rep.get("status") == 400:
            return "error", "replay_error"
        return "error", "official_error"

    trans = rep.get("input_transformations")
    if trans is None:
        return "pass", "no_diagnostics"
    ours = [t for t in trans if t.get("path") in paths] or trans
    reasons = {t.get("reason") for t in ours}
    if "model_binding_mismatch" in reasons:
        return "forged", "model_mismatch"
    if "prefix_binding_mismatch" in reasons:
        return "suspicious", "prefix_mismatch"
    if reasons - {"organization_binding_mismatch"}:
        return "suspicious", "unknown_transformation"
    if reasons:
        return "pass", "org_binding"
    return "pass", "verified"


# ---------------------------------------------------------------- helpers


def _is_b64(s: str) -> bool:
    try:
        base64.b64decode(s, validate=True)
        return True
    except ValueError:
        return False


def heuristics(m: dict, requested_model: str) -> dict:
    data = m.get("raw") or {}
    content = data.get("content") or []
    thinking = [b for b in content if isinstance(b, dict) and b.get("type") == "thinking"]
    tool = next((b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"), None)
    usage = data.get("usage") or {}
    sig = thinking[0].get("signature", "") if thinking else ""
    answer = (tool or {}).get("input", {}).get("answer") if tool else None
    nonce = (tool or {}).get("input", {}).get("nonce") if tool else None
    challenge = m.get("challenge") or {}
    return {
        "id": data.get("id"),
        "id_prefix_ok": str(data.get("id", "")).startswith("msg_"),
        "model_echo": data.get("model"),
        "model_match": data.get("model") == requested_model,
        "usage_ok": isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "stop_reason": data.get("stop_reason"),
        "thinking_blocks": len(thinking),
        "signature_len": len(sig),
        "signature_b64": _is_b64(sig) if sig else None,
        "thinking_text_nonempty": any(b.get("thinking") for b in thinking),
        "has_tool_use": tool is not None,
        "answer_correct": (answer == challenge.get("expected")) if tool else None,
        "nonce_ok": (nonce == challenge.get("nonce")) if tool else None,
        "latency_ms": m.get("latency_ms"),
        "attempts": m.get("attempts"),
    }
