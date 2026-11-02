"""Models under test and their first-party prices (USD per 1M tokens)."""

MODELS = [
    {
        "id": "claude-opus-5-5",
        "name": "Claude Opus 5.5",
        "input": 4.00,
        "output": 20.00,
        "note": "",
    },
    {
        "id": "claude-sonnet-5-5",
        "name": "Claude Sonnet 5.5",
        "input": 2.00,
        "output": 10.00,
        "note": "账号绑定：回放必然出现 organization_binding_mismatch，属正常",
    },
    {
        "id": "claude-haiku-5-5",
        "name": "Claude Haiku 5.5",
        "input": 0.10,
        "output": 0.50,
        "note": "账号绑定：回放必然出现 organization_binding_mismatch，属正常",
    },
    {
        "id": "claude-fable-5-1",
        "name": "Claude Fable 5.1",
        "input": 10.00,
        "output": 50.00,
        "note": "官方账号需开启 30 天数据保留（ZDR 账号会 400）",
    },
]

MODEL_IDS = [m["id"] for m in MODELS]
_BY_ID = {m["id"]: m for m in MODELS}


def cost_of(model_id: str, usage: dict | None) -> float:
    """Price a response's usage at first-party rates."""
    if not usage:
        return 0.0
    m = _BY_ID.get(model_id)
    if not m:
        return 0.0
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0
    total = (
        inp * m["input"]
        + cache_write * m["input"] * 1.25
        + cache_read * m["input"] * 0.1
        + out * m["output"]
    )
    return round(total / 1_000_000, 6)
