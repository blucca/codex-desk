# Blucca engineering sample: native MCP results that survive reopening

**Recorded November 25, 2026 · Linux · Codex CLI 0.171.0**

## One native turn, two tool calls

Blucca exercised its own Codex Desk project through the native app-server with a **local, read-only synthetic MCP server**. The task requested `desk_acceptance_report` exactly twice: `case="success"`, then `case="error"`, followed by one sentence summarizing both results.

The recorded turn completed, with these individual tool outcomes:

| Call | Native status | Original result text |
|---|---|---|
| `{"case":"success"}` | `completed` | `Synthetic local acceptance: three checks passed` |
| `{"case":"error"}` | `failed` | `Deliberate acceptance error: fixture unavailable` |

The success result also retained this original `structuredContent`:

```json
{"fixture":"local-only","passed":3}
```

Both native items carried `readOnlyHint: true` and `error: null`. The failed item's diagnostic lived in `result.content`; its `structuredContent` was `null`. The fixture's raw response used `isError: true`, which became a native call with `status: failed`. A renderer needs the **individual tool status and result text**, even when the enclosing turn completes.

Recorded final answer:

> The success case passed three checks, and the error case deliberately reported “fixture unavailable.”

## Repair the presentation boundary, then reopen

The initial browser check received both native calls but failed to show the success text, structured result and reviewed handoff evidence. The new renderer asset, `/evidence.js`, was missing from the HTTP static registry.

The repair registered that asset with its JavaScript MIME type and added a regression check that loads the served page, discovers its referenced assets and verifies their HTTP responses, MIME types and packaged bytes.

A fresh Desk runtime then reopened **the same used native conversation**, with **zero additional model turns**. Its recorded browser checks passed for:

- Both original result texts and the structured success result in activity.
- Both result texts in the reviewed handoff.

A separate offline replay of that saved history and its events verified five visible cards in order: user request → assistant pre-tool message → success call → failed call → final answer. This replay also used zero model turns.

The native history still contained the original one turn. The acceptance task produced **zero command-execution or file-change items**, and the main Codex configuration remained unchanged.

## Native-reported usage

The final native usage snapshot reported these cumulative counters:

| Counter | Tokens |
|---|---:|
| Input | 37,703 |
| Cached input, included in input | 13,591 |
| Output | 254 |
| Total | 37,957 |

The latest reported request was **11,499 tokens**, included within the cumulative total above.

## Run the two response cases offline

The [synthetic stdio fixture](../examples/native_mcp_fixture.py) preserves the exact success and deliberate-error responses used in this recording. From the repository checkout, with Python 3:

```sh
python3 examples/check_native_mcp_fixture.py
```

Expected stdout:

```text
PASS: 2 tool-call cases; initialize/list/ping verified
```

The [check script](../examples/check_native_mcp_fixture.py) sends initialization, tool discovery, the two calls and a ping over stdin/stdout, and checks five replies plus the exact success/error payloads. It needs no account, model or network connection.

## Inspect the implementation

- [Native tool-evidence formatter](../codex_desk/evidence.py)
- [Reviewed handoff builder](../codex_desk/handoff.py)
- [Focused tool-result tests](../tests/test_tool_evidence.py)
- [Served-asset regression test](../tests/test_assets.py)
