# Claude 中转站签名检测

本地网页工具：用 Anthropic 官方 API 校验第三方中转站返回的 thinking 签名，判断中转站提供的 Claude 是否掺假。

## 原理

1. **铸造**：用中转站的 URL + Key 请求一道带随机验证编号的计算题，要求用普通文本给出答案与验证编号，拿到带 `signature` 的 thinking 块与文本回复。
2. **相关性追问**：向同一中转站发送第一轮的完整对话，保留原始 thinking、签名与文本回复，再用普通用户消息询问“刚才的思考是否与题目有关？只回答是或不是”。完整回答“是”，或响应的 `stop_details` 中 `type` 为 `refusal` 且 `category` 为 `reasoning_extraction` 时，继续官方回放；该拒绝仅表示不允许提取思考，不代表确认相关，最终结论由官方回放决定。其他情况下，回答“不是”按检测规则记为 **签名复用**，其他回答记为 **无法检测**，请求失败记为 **出错**，均跳过官方回放。
3. **回放**：满足上述继续条件后，把第一轮的 assistant 回合原样放回对话，追加普通用户消息，用官方 Key 发给官方 API。官方会解密并校验签名：
   - 伪造或篡改的签名 → 400 `Invalid signature in thinking block` → **掺假**
   - 真签名 → 200。回放时带上 `thinking-binding-controls-2026-08-01` beta 头，官方会在 `input_transformations` 里说明是否丢弃了这个块、原因是什么：
     - `model_binding_mismatch`：签名不是声称的模型生成的 → **掺假（模型替换/降级）**
     - `prefix_binding_mismatch`：中转站改动了上下文，比如注入 system prompt → **通过**
     - `organization_binding_mismatch`：来自其他账号。Sonnet 5.5 / Haiku 5.5 有账号绑定，属正常 → **通过**

不再运行阳性或阴性对照。正常每轮调用中转站 2 次、官方 API 最多 1 次；没有拿到 thinking 时，首轮最多尝试 3 次，SDK 自动重试另计。追问与首轮均按所选流式/非流式方式发送，两次中转站调用的 usage 一并计入费用。旧对照记录与历史费用保留在数据库及导出数据中。

## 启动

需要 Python 3.10+。

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
.venv/bin/python run.py                        # 打开 http://127.0.0.1:8765
```

参数：`--port 8765` 指定端口，`--no-browser` 启动后不自动打开浏览器。

## 使用

1. **官方 Key 与设置**：添加官方 Anthropic API Key（`sk-ant-…`），可以存多个并设一个默认；检测使用的 `system` 文本块数组可在设置中直接编辑。
2. **中转站**：添加名称、Base URL、Key。如果中转站改了模型名，在「模型名映射」里填写。
3. **发起检测**：多选中转站 × 模型，设置轮数和请求方式，在任务页实时查看结果。
4. **检测记录**：每轮依次展示中转站首轮、相关性追问与官方回放结果，追问原文和完整响应随 JSON 导出。在详情底部「官方上游请求与响应」展开各次调用，可查看完整请求体、完整响应、HTTP 状态和 Request ID；默认显示原文，可勾选「格式化 JSON」方便阅读。检测期间自动刷新，SDK 重试逐次列出。这些内容也包含在导出的 JSON 中。

## 数据与安全

- 所有数据，包括中转站与官方 Key（明文），都保存在 `data/signature.db`。`data/` 已加入 `.gitignore`。
- 官方 Key 发出的每次请求都会在发送前写入 `official_requests` 表，包含时间、Key ID、任务 ID、请求方法、URL 和完整原始请求体 `request_body`（UTF-8 文本，不截断）。收到响应后，保存完整响应文本 `response_body`、`status_code` 和 `response_request_id`，包括非 JSON 错误页；未收到完整响应时 `response_body` 为 `NULL`，响应体为空时为 `''`。检测请求还关联记录、模型、阶段和轮次，覆盖正常回放以及 SDK 自动重试；Key 连通性测试的 GET 请求体为空，任务 ID 为空。请求日志不保存鉴权头，删除任务或 Key 后仍保留。重启服务时自动兼容旧数据库，历史缺失的请求与响应无法补录。可用 `SELECT * FROM official_requests ORDER BY id DESC;` 查询。
- 服务只监听 `127.0.0.1`，局域网访问不到。
- 页面上 Key 打码显示，导出的记录不含 Key。删除中转站时会清空它的 Key，历史记录保留。

## 局限

- 相关性追问是中转站模型的自述，不能证明正文与 thinking 绑定，也不能单凭“是”排除签名复用。官方回放校验的是 thinking 签名，不保证回复正文由 Claude 生成或答案正确。中转站可能只把检测请求转给真 Claude；怀疑按比例掺假时请调高轮数。
- 模型读取关系是单向的（例如在 Claude API 上，Opus 5.5 能读 Sonnet 5.5 的块），所以模型替换只能部分识别。
- 中转站必须支持 Anthropic 原生 `/v1/messages`，并原样透传 thinking 与 signature。
- 只有相关性追问完整回答“是”，或响应的 `stop_details` 中 `type` 为 `refusal` 且 `category` 为 `reasoning_extraction` 的轮次才会消耗官方回放额度：回放请求用低 effort、`max_tokens` 1024，实际花费按 usage 记录在每条记录里。
