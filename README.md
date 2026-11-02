# Claude 中转站签名检测

本地网页工具：用 Anthropic 官方 API 校验第三方中转站返回的 thinking 签名，判断中转站提供的 Claude 是否掺假。

## 原理

1. **铸造**：用中转站的 URL + Key 请求一道带随机验证编号的计算题，拿到带 `signature` 的 thinking 块（以及一次工具调用）。
2. **回放**：把这个 assistant 回合原样放回对话，用官方 Key 发给官方 API。官方会解密并校验签名：
   - 伪造或篡改的签名 → 400 `Invalid signature in thinking block` → **掺假**
   - 真签名 → 200。回放时带上 `thinking-binding-controls-2026-08-01` beta 头，官方会在 `input_transformations` 里说明是否丢弃了这个块、原因是什么：
     - `model_binding_mismatch`：签名不是声称的模型生成的 → **可疑（模型替换）**
     - `prefix_binding_mismatch`：中转站改动了上下文，比如注入 system prompt → **可疑**
     - `organization_binding_mismatch`：来自其他账号。Sonnet 5.5 / Haiku 5.5 有账号绑定，属正常 → **通过**
3. **对照实验**（每次都跑）：
   - 阳性对照：官方铸造 → 官方回放，必须通过（每个任务每个模型跑一次）
   - 阴性对照：把中转站的签名改几个字节 → 官方回放，必须被拒绝（每项跑一次）
   - 任一对照失败，结论记为 **检测无效**

## 启动

需要 Python 3.10+。

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
.venv/bin/python run.py                        # 打开 http://127.0.0.1:8765
```

参数：`--port 8765` 指定端口，`--no-browser` 启动后不自动打开浏览器。

## 使用

1. **官方 Key 与设置**：添加官方 Anthropic API Key（`sk-ant-…`），可以存多个并设一个默认。
2. **中转站**：添加名称、Base URL、Key。如果中转站改了模型名，在「模型名映射」里填写。
3. **发起检测**：多选中转站 × 模型，设置轮数和请求方式，在任务页实时查看结果。
4. **检测记录**：每条记录都能看到两个对照实验、每轮的中转站响应和官方回放结果，可以导出 JSON 作为证据。

## 数据与安全

- 所有数据，包括中转站与官方 Key（明文），都保存在 `data/signature.db`。`data/` 已加入 `.gitignore`。
- 服务只监听 `127.0.0.1`，局域网访问不到。
- 页面上 Key 打码显示，导出的记录不含 Key。删除中转站时会清空它的 Key，历史记录保留。

## 局限

- 只能证明**这一次**回复来自真 Claude。中转站可能只把带 thinking 的请求转给真 Claude；怀疑按比例掺假时请调高轮数。
- 模型读取关系是单向的（例如在 Claude API 上，Opus 5.5 能读 Sonnet 5.5 的块），所以模型替换只能部分识别。
- 中转站必须支持 Anthropic 原生 `/v1/messages`，并原样透传 thinking 与 signature。
- 每项检测都会消耗官方额度：回放请求用低 effort、`max_tokens` 1024，实际花费按 usage 记录在每条记录里。
