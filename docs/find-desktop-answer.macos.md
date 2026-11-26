# Find an old answer in local Codex Desktop history on macOS

Remember the issue number or a phrase from an answer, but not the chat title? Desk indexes saved native Codex conversations and opens a match at its original message or tool result.

## Use the Codex already bundled with Desktop

In Terminal, check the bundled version:

```sh
/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex --version
```

This is the native executable in the current ChatGPT Desktop bundle. With [uv](https://docs.astral.sh/uv/getting-started/installation/), launch Desk with that same executable; a separate Codex CLI installation is not needed:

```sh
uvx --prerelease allow codex-desk --codex /Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex
```

Keep Terminal running and open the printed local URL. For an app installed somewhere else, adjust the app path and quote it if it contains spaces. Older Codex Desktop bundles use `/Applications/Codex.app/Contents/Resources/codex`; the [official troubleshooting guide](https://developers.openai.com/codex/app/troubleshooting/) documents that earlier path. Check the executable that exists in your installed bundle before choosing it.

## Find and read the original

1. Choose **Find a decision in past work**.
2. Choose **Index existing Codex history**. The explicit scan reads up to 200 recently updated native conversations into Desk's local cache.
3. Search a distinctive issue ID or a phrase from the answer. Search is literal and case-insensitive; conversation titles and saved content are separate searches.
4. Choose **Read original conversation** on the matching result. Inspect the original message, command output or tool evidence, then use **Back to search** to keep your phrase and results.

The history comes from this Mac's Codex home: `--codex-home` if supplied, otherwise the `CODEX_HOME` environment variable if set, otherwise `~/.codex`. This is local **Codex** history; ChatGPT web chats and Desktop **Work** history use separate histories. The [official guide](https://developers.openai.com/codex/app/troubleshooting/) identifies native session transcripts under `$CODEX_HOME/sessions` and `$CODEX_HOME/archived_sessions`.

## Return when the issue comes up again

Relaunch using the same executable and any original `--codex-home`, `--state-dir` and `--port` options. Indexed evidence stays in Desk's local cache. You can read an original even after its project folder has been removed. If the folder still exists and you want to resume work, **Continue this conversation** opens the same native thread; prepare an unsent draft and choose when to send it.

Desk runs its own app-server with the selected binary. It uses your native Codex configuration and sign-in rather than attaching to the running Desktop backend. History indexing and reading send no model task.

## Reproduce bundled-runtime compatibility

Delivered Desk **0.1.0a30** passed native list → explicit index → two phrase hits → exact original → restart-cache acceptance with the official macOS bundle's **codex-cli 0.171.0-alpha.13.2**. The fixture uses isolated synthetic `vscode` and `cli` legacy histories, with an `exec` source excluded by the normal native source filter. No model tasks or personal Desktop histories are used in this check.

[Bundled-history checker](../examples/check_desktop_history.py) · [Manual macOS acceptance workflow](../.github/workflows/desktop-history.yml)

[Try the labeled browser sample](https://blucca.github.io/codex-desk/demo/) · [Installation and launch options](../README.md#install-the-preview)
