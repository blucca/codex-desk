# One project task. The same conversation when you return.

**Codex Desk** — find a saved conversation, read its tool evidence, give it one next task, then return to the same native thread.

![Five-panel Codex Desk walkthrough: exact project and title search, saved MCP success and deliberate failure, an unsent verification task, same-session return, and optional reviewed handoff](images/task-walkthrough.png)

*Own local example: synthetic native MCP results from CLI 0.171.0/Linux, replayed in alpha10's shipped UI with a controlled local transport. Native items and thread ID preserved; folder relocated. Verification is an unsent draft; handoff is review-only. Prior native acceptance checked same-ID restart.*

## Install and open

Requires **Python 3.11+** and a complete, configured [Codex CLI](https://developers.openai.com/codex/cli). Check `codex --version` in the shell you will use for Desk.

Follow the [maintained installer](../README.md#install-the-preview), choosing **Linux/macOS/WSL** or **Windows PowerShell** commands. It creates an isolated installation and installs the current published preview without Git. Launch Desk, then open its printed loopback URL, normally **http://127.0.0.1:8787**. [中文 first-project guide](first-project.zh-CN.md).

## A 90-second walkthrough

**0–15s · Find the work.** Choose **Open a project**, enter its exact saved working directory, and keep **Current Codex settings**. Enter part of your conversation title, then choose **Find existing sessions** and resume it. This example searches “Native MCP” and opens **Native MCP tool evidence**. Search matches titles, not tool output; use **Browse existing Codex sessions** across folders.

**15–35s · Read the result.** Expand both MCP cards: three synthetic checks passed, with `passed: 3` in the structured result; the deliberate failure says “fixture unavailable.” Read the tool evidence alongside the summary.

**35–55s · Give it one next task.** Choose **Work — native tools and edits** and enter:

```text
Find this project's verification command in README, run it, and report the exact command, output and exit status. Do not install dependencies or edit files.
```

Click **Run task** in your project. Review any native command approval, then check actual output and exit status.

**55–80s · Return.** Close the page, reopen the printed URL, and choose the same named session. To restart Desk, press **Ctrl+C**, then relaunch below using the original Codex home and state directory. The saved used conversation resumes its original native thread.

**80–90s · Optional branch.** **Continue with another provider** opens a handoff to review. Choose the next goal and profile. **Start new native conversation** creates a distinct thread, keeping the original intact.

## Next launch — no reinstall

```sh
cd "$HOME/codex-desk-install"
. .venv/bin/activate
codex-desk
```

Reuse any original `--codex`, `--codex-home` and `--state-dir` arguments. Stopping Desk also stops its owned native tasks; closing just the browser leaves the backend running.

## Full-size panels

[1 · Find](images/task-walkthrough-01-find.png) · [2 · Read](images/task-walkthrough-02-read.png) · [3 · Task draft](images/task-walkthrough-03-task-draft.png) · [4 · Return](images/task-walkthrough-04-return.png) · [5 · Handoff review](images/task-walkthrough-05-handoff-review.png)

[1200×630 overview card](images/task-walkthrough-card.png). For a task you want to finish, [ask for project-task help](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml) with your CLI version, operating system, task and step reached.
