# Find an old answer with the Codex reader in the installed Windows app

Remember an issue number or a phrase from a Codex answer, but not its conversation title? Desk can index saved native conversations and open the matching original message or tool result.

If the Windows app is already installed for your account, check its bundled native executable before installing another Codex CLI.

## Find and check the existing reader

In your ordinary PowerShell terminal, find the package registered for your account:

```powershell
$package = Get-AppxPackage -Name OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1
$package | Select-Object Name, Version, InstallLocation
```

When this returns the installed package and its location, check the native executable:

```powershell
$codex = Join-Path $package.InstallLocation 'app\resources\codex.exe'
& $codex --version
```

Use this route when the version check succeeds in that same ordinary terminal. If the package is absent or Windows denies access to its executable, use the [standalone Codex CLI entry](../README.md#install-the-preview). Keep the app installation and WindowsApps permissions as they are.

## Launch and find the original

With [uv](https://docs.astral.sh/uv/getting-started/installation/), pass the checked executable to Desk:

```powershell
uvx --prerelease allow codex-desk --codex "$codex"
```

Keep PowerShell running and open the printed local URL.

1. Choose **Find a decision in past work**.
2. Choose **Index existing Codex history** to read up to 200 recently updated native conversations into Desk's local cache.
3. Search the remembered issue number or phrase. Search is literal and case-insensitive; title search is separate from saved-content search.
4. Choose **Read original conversation** to inspect the original message or tool evidence. **Back to search** keeps your phrase and results.

The source is this account's local Codex home: `--codex-home` if supplied, otherwise `CODEX_HOME` if set, otherwise `%USERPROFILE%\.codex`. ChatGPT web conversations and Desktop Work use separate histories. The [official troubleshooting guide](https://developers.openai.com/codex/app/troubleshooting/) describes local Codex transcripts under `$CODEX_HOME/sessions` and `$CODEX_HOME/archived_sessions`.

## Return to the saved evidence

Next time, repeat the package lookup and successful version check, then launch with the same `--codex-home`, `--state-dir` and `--port` options you originally used. The installed package location can change when the app updates; Desk's local cache and preparation belong to your retained state directory.

You can read original evidence after its project folder has been removed. If the folder exists and your next task belongs in that thread, **Continue this conversation** resumes the same native ID. Prepare the next instruction and choose when to send it. Desk runs its own app-server with the selected executable and inherits your native configuration and sign-in. History indexing and reading send no model task.

## Measured installed-package checkpoint

The official signed **OpenAI.Codex 26.1120.6357.0** package was provisioned with its public offline license on **Windows Server 2025, build 26100**, then registered for a separate standard user with a loaded profile. That non-administrator account successfully invoked `app\resources\codex.exe` directly from its OS-installed WindowsApps location: **codex-cli 0.171.0-alpha.13.2**, delivered **Desk 0.1.0a30**.

The isolated synthetic legacy `vscode`/`cli` fixture passed list → explicit index → two phrase hits → exact original messages → cache after restart. No manual WindowsApps ACL or ownership changes were made. The fixture preserves config/auth and original rollouts and sends no model tasks. Consumer Store installation and personal Desktop-created history are separate checkpoints; your own ordinary-user version check selects this entry.

[Try the labeled browser sample](https://blucca.github.io/codex-desk/demo/) · [Installation and launch options](../README.md#install-the-preview)
