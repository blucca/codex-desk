# Search a saved native answer by phrase

[`find_native_answer.py`](../examples/find_native_answer.py) searches assistant text and command output from one saved Codex conversation using only the Python standard library. Each match retains its original thread, turn and item IDs, plus the first 200 characters of original text.

## Run the synthetic example

From the repository root:

```sh
python3 examples/find_native_answer.py examples/native-answer-snapshot.json "retry budget"
```

The [synthetic snapshot](../examples/native-answer-snapshot.json) contains an assistant answer, matching command output and a command with null output. Expected output:

```json
{"threadId": "synthetic-checkout-thread", "turnId": "synthetic-turn", "itemId": "synthetic-answer", "preview": "RETRY BUDGET: retain the original retry limit."}
{"threadId": "synthetic-checkout-thread", "turnId": "synthetic-turn", "itemId": "synthetic-command", "preview": "Retry budget verified: 2 attempts retained."}
```

Search uses NFKC normalization followed by casefold and literal substring matching. Fullwidth `ＲＥＴＲＹ ＢＵＤＧＥＴ` returns the same two IDs. The phrase `.*` returns zero matches: punctuation is literal. Null text/output is treated as empty. Preview text and IDs stay in their original form.

## Use a native snapshot

Save the **`result` object** from a `thread/read` JSON-RPC response as `snapshot.json`. Request the saved turns/items with `includeTurns: true` from an initialized Codex app-server client:

```json
{"id":2,"method":"thread/read","params":{"threadId":"<saved-thread-id>","includeTurns":true}}
```

The input has a top-level `thread` with its original `id` and `turns` array. Each turn has an `id` and `items` array; each item has its original `id` and `type`. The example searches `agentMessage.text` and `commandExecution.aggregatedOutput` strings, keeping one JSON output line per matching item.

```sh
python3 examples/find_native_answer.py snapshot.json "phrase from your saved answer"
```

`thread/list`'s `searchTerm` filters the extracted conversation title. This example searches the supplied body instead. Use the returned thread/turn/item IDs to locate the original answer in that snapshot or a fresh native history read.

[Native read contract, Codex 0.171](https://github.com/openai/codex/blob/rust-v0.171.0/codex-rs/app-server-protocol/schema/json/v2/ThreadReadParams.json) · [Browser history search and original reader](find-past-answer.md)
