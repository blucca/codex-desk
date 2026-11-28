# Blucca engineering sample: project tests and native runtime restart

**Recorded November 25, 2026 · Linux · Codex CLI 0.171.0**

## One project, one test task

Blucca ran its own Codex Desk persistence/profile unit checks through the native app-server. The task requested one test command and the exact pass count.

Requested command, with the scratch directory normalized:

```sh
DESK_TEST_TEMP="$PWD/temp/native-proof" PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Recorded command output:

```text
test_profiles_do_not_expose_keys_or_rewrite_base (test_runtime.PersistenceTests.test_profiles_do_not_expose_keys_or_rewrite_base) ... ok
test_reopen_and_latest_usage (test_runtime.PersistenceTests.test_reopen_and_latest_usage) ... ok

----------------------------------------------------------------------
Ran 2 tests in 0.024s

OK
```

**One native command completed; exit code 0.** The completed native answer reported exactly two passing tests.

## Reopen the used conversation

The harness closed the owned app-server, constructed a new Desk runtime and reopened the saved conversation. Recorded checks:

```json
{
  "resumeSameThread": true,
  "resumedTurnCount": 1,
  "commandOutputPresent": true,
  "baseConfigUnchanged": true,
  "authUnchanged": true
}
```

Native history returned the prior task, completed command/output and answer. The reopened runtime reported the same usage counters for that completed turn.

| Native-reported cumulative counter | Tokens |
|---|---:|
| Input | 30,058 |
| Cached input, included in input | 9,770 |
| Output | 164 |
| Total | 30,222 |

## Inspect and reproduce

- [Recorded source](https://github.com/blucca/codex-desk/blob/c685ef47e96c9499841d8f6df513b33c965b17fe/tests/test_runtime.py)
- [Native saved-thread resume implementation](https://github.com/blucca/codex-desk/blob/c685ef47e96c9499841d8f6df513b33c965b17fe/codex_desk/runtime.py#L181-L198)
- [Current project/task/reopen walkthrough](https://github.com/blucca/codex-desk/blob/main/docs/task-walkthrough.md)

## Native MCP integration sample

[Read the MCP result/reopen recording](native-mcp-example.md): one native turn calls a read-only synthetic tool twice, preserves its success and deliberate error, and reopens the same used conversation. A runnable stdio fixture reproduces both response cases offline.
