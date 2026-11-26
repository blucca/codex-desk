# Search a saved native answer by phrase

[`find_native_answer.py`](../examples/find_native_answer.py) searches assistant text and command output from one saved Codex conversation using only the Python standard library. Each match retains its original thread, turn and item IDs, plus the first 200 characters of original text.

## Choose the native search scope first (Codex 0.171)

`thread/list.searchTerm` filters extracted titles. Codex also has experimental native message-body search; the title filter and this snapshot exercise are separate interfaces.

| Evidence you need | Route |
| --- | --- |
| A remembered conversation title | `thread/list` with `searchTerm`. |
| A user/assistant phrase across eligible saved histories | Experimental `thread/search`: each result has `thread` and one verified message `snippet`. |
| Exact message occurrences in one paginated thread | Experimental `thread/searchOccurrences`: user text and partial/final assistant answers. |
| Tool output in a known conversation | `codex resume <thread-id>` → **F3 Find** searches the detailed transcript, including collapsed tool text, and requests earlier history as needed. |
| Assistant text or captured command output in one supplied snapshot | The Python exercise below searches `agentMessage.text` and `commandExecution.aggregatedOutput` for items present in that file. |

For an existing app-server client, enable experimental methods on the connection:

```json
{"id":0,"method":"initialize","params":{"clientInfo":{"name":"history_scope_example","title":"History scope example","version":"1.0"},"capabilities":{"experimentalApi":true}}}
```

After the initialization response, send the notification, then a search request as separate messages:

```json
{"method":"initialized"}
{"id":3,"method":"thread/search","params":{"searchTerm":"retry budget","limit":25,"currentAccountOnly":false}}
```

Take a returned `data[].thread.id`. For a paginated thread, request exact occurrences:

```json
{"id":4,"method":"thread/searchOccurrences","params":{"threadId":"<paginated-thread-id>","searchTerm":"retry budget","limit":50}}
```

Global search defaults to interactive, non-archived histories; `sourceKinds`, `archived`, `currentAccountOnly` and `includeAttachedThreads` control eligibility. Its default/maximum `limit` is **25/100 results per page**; occurrences use **50/250 per page**. These are page sizes, not total-history coverage limits. Continue with `nextCursor` as the next request’s `cursor`, keeping the query, selected eligibility and sort fields unchanged. For occurrences retain the same `threadId` and `searchTerm`.

Each occurrence supplies `turnId`, `itemId`, `snippetMatchRange` (start-inclusive/end-exclusive UTF-16 offsets within `snippet`) and `turnCursor`, an inclusive cursor for `thread/turns/list`. Use those identities to inspect the original item; `nextCursor` instead continues the occurrence search.

Tool-only command/MCP/dynamic-result items are outside these two API search scopes. Known-thread transcript Find and searching supplied command output remain useful for that evidence. F3 uses **Ctrl+P** for older matches, **Ctrl+N** for newer, **Enter** to accept and **Esc** to cancel or return to latest. **Ctrl+T** opens the transcript pager, where F3 or `/` also starts Find; custom bindings follow `/keymap`.

Immutable 0.171 sources: [initialization][native-initialize] · [wire methods][native-wire] · [search fields and occurrence identities][native-fields] · [global page size][native-global-limit] · [occurrence page size][native-occurrence-limit] · [searchable message types][native-message-types] · [global snippet verification][native-global-messages] · [transcript Find][native-find] · [default keys][native-keys] · [pager keys][native-pager-keys] · [Find navigation][native-find-navigation].

[native-wire]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/app-server-protocol/src/protocol/common.rs#L881-L916
[native-fields]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L1550-L1757
[native-global-limit]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/app-server/src/request_processors/thread_processor.rs#L67-L68
[native-occurrence-limit]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/app-server/src/request_processors/thread_processor.rs#L6336-L6337
[native-message-types]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/thread-store/src/local/thread_history/search.rs#L311-L368
[native-global-messages]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/rollout/src/search.rs#L321-L367
[native-find]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/tui/src/transcript_view/search.rs#L1-L6
[native-keys]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/tui/src/keymap.rs#L1908-L1910

[native-initialize]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/app-server-protocol/src/protocol/common.rs#L2918-L2970

[native-pager-keys]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/tui/src/keymap.rs#L2153-L2164
[native-find-navigation]: https://github.com/openai/codex/blob/ccf9be8cc458bd6b8336fe84d68d8893f2691a5e/codex-rs/tui/src/transcript_view/search_footer.rs#L45-L106

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
