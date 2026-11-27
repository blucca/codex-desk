# Codex Desk：找回旧答案，先阅读，再继续任务

记得答案中的一句话，却忘了会话标题？用已有的 Codex CLI 和登录，索引本机历史、查找文字并阅读原会话；准备好后再续接同一个任务。界面目前使用英文，下面保留实际按钮名称。

[免安装交互示例](https://blucca.github.io/codex-desk/demo/)：在合成会话中查找 `retry budget`、阅读原文、保存 Plan 草稿，再刷新回来。示例准备保存在当前浏览器；使用自己的 Codex 历史时按下方安装。

[20 秒示例：索引 → 查找答案 → 阅读原会话](find-answer.gif)（合成的结账项目历史）

## 1. 安装并启动

独立 CLI：在准备启动 Desk 的终端确认 `codex --version` 可用；它显示的是原生 Codex CLI 版本。只有 Desktop 内置 Codex 时，按 [macOS](find-desktop-answer.macos.md) 或 [Windows](find-desktop-answer.windows.md) 指南检查所选可执行文件，并用 `--codex` 传给 Desk，无需另装 CLI。按 [README 维护中的安装步骤](../README.md#install-the-preview)启动；使用 Python 安装时，展开对应系统的虚拟环境步骤，需要 Python 3.11+。

独立 CLI 使用 uv 时运行（Desktop 内置版本使用上方系统指南中的 `--codex` 命令）：

```sh
uvx --prerelease allow codex-desk
```

保持终端运行，打开它打印的完整 URL（通常位于 `http://127.0.0.1:8787`，带有此次启动的访问片段）。如果地址已占用，使用原有 Desk 终端中打印的完整 URL 返回仍在运行的服务；要换成更新后的版本，先在旧终端按 **Ctrl+C** 再启动。需要换端口时，在启动命令后加 `--port 8788`。端口占用不会创建或修改 Desk 记录。如果 Codex 历史位于其他目录，在启动命令后加 `--codex-home /你的目录`。Windows 与 WSL 使用各自启动环境中可访问的 Codex home 和项目路径。

原生目录列表和原文阅读使用 `--codex-home`，未指定时使用 `CODEX_HOME`，否则使用当前启动环境的 `~/.codex`。正文搜索使用 `--state-dir` 中保留的数据库；只更换 Codex home 不会清除原有匹配。切换到另一套历史时，同时指定不同的 `--state-dir`，保留旧目录和启动参数以便返回原有准备内容。阅读旧匹配的原文时，用原来的 home 和 state directory 启动。

### 更新已缓存的 uvx 预览

uvx 可能复用缓存中的旧版 Desk。需要更新时，先在旧 Desk 启动终端按 **Ctrl+C**，再运行一次：

```sh
uvx --refresh --prerelease allow codex-desk@latest
```

以后仍用普通的 `uvx --prerelease allow codex-desk` 启动。更新和以后启动时，都附上原有的 `--codex`、`--codex-home`、`--state-dir` 和 `--port` 参数；保持同一 state directory，会话、索引、草稿和准备列表留在原数据库。uvx 选中的 Desk 软件包版本用 `uvx --prerelease allow codex-desk --version` 查看；原生版本用启动时所选可执行文件的 `--version` 检查。独立 CLI 使用 `codex --version`，Desktop 内置版本按上方系统指南检查。

## 2. 按答案中的文字查找

1. 首页点击 **Find a decision in past work**；已有会话打开时，点击侧栏 **Search saved content**。
2. 点击 **Index existing Codex history**，明确读取最近更新的最多 **200 个原生会话**，包括尚未在 Desk 打开过的历史。等状态显示完成，核对 seen／indexed／unchanged／failed 数量。索引只读取历史并保存本地缓存，不创建会话绑定或发送任务。
3. 先保持 **All indexed projects**。在 **Saved content query** 输入旧答案、命令输出或工具结果中实际出现的 **2–200 个字符**，再点击 **Search** 或按 Enter。索引进行中也可以提交查询；明确启动的索引完成后，仍在当前搜索对话框中、未修改的已提交查询会自动刷新一次。搜索按字面文字匹配，忽略大小写并规范化 Unicode。修改文字或范围后，点击 **Search** 提交修改。
4. 核对结果中的会话、项目目录和匹配片段。需要缩小范围时，选择 **Project folder (optional)**，再点 **Search**。

**Index coverage and text limits** 显示实际缓存范围和缩短／省略的条目。**Refresh recent history** 刷新最近 200 个会话并跳过未变化的快照。**Index next older conversations** 明确继续读取更旧的一组历史，沿用已保存的分页进度。**Cancel indexing** 保留已缓存的内容和未读分页条目；取消或重启后用 **Continue indexing** 继续，失败的原文读取用 **Retry unread histories** 重试。关闭搜索对话框后，正在进行的索引仍会继续。

索引完成时会保留未提交的修改、正在阅读的原会话、结果焦点和导航选择。关闭搜索对话框或正在查看已有结果时，返回后用 **Search** 更新匹配。仍在等待响应的已提交查询会先完成，再执行一次新查询；新提交的查询优先于旧响应。

## 3. 只读原会话

在原生历史结果或带有原 thread 的缓存活动结果中，点击 **Read original conversation**。查看器定位原 turn／item，并高亮匹配文字；当前打开的任务和草稿保持不变。

**项目目录已删除，也能阅读原历史。** 阅读不导入、不续接 thread。点击 **Back to search** 或 **Close** 返回原查询和结果。

长会话每页最多显示 **40 个条目**（原生内容项或未产生内容项的回合结果），用 **Previous items**／**Next items** 换页；含无内容项回合时按钮为 **Previous entries**／**Next entries**。没有内容项的回合仍显示原生 ID、状态和已报告的错误信息，计数与原始内容项分开。长输出用 **Earlier text**／**Later text** 阅读其他文字窗口，每个窗口最多 **20,000 个字符**。原匹配项已变化时，查看器显示实际定位状态；读取失败用 **Retry read** 重试。

**Find in this original conversation** 查找本次读取提供的全部可读文字，包括其他条目页和超出缓存前缀的长输出。输入文字后点 **Find**，用 **Previous match**／**Next match**，或查看器中的 Shift+F3／F3 跳转。**Copy full item text** 复制整个可读内容项，**Copy source reference** 复制会话及原生 thread／turn／item／项目目录标识。正文结果的 **Previous matches**／**Next matches** 可查看后续匹配页；从原文返回后保留当前结果页。

### 已知标题，或会话不在近期索引里

首页点击 **Browse all conversations**，或侧栏 **Browse existing Codex sessions**。输入标题文字，点击 **Search titles**，需要时用 **Load more**。在该行直接点击 **Read original conversation**，无需先续接，也不要求原目录存在。返回后保留标题查询和已加载列表。

标题搜索不搜索正文。若要把更旧会话的正文加入内容搜索，用 **Index next older conversations** 延伸索引；也可在目录存在时明确续接，打开后的可读活动会缓存到 Desk。

指定项目时，可在 **Open a project** 输入原来保存的完整目录，即使目录已删除，**Find existing sessions** 仍能按该目录搜索标题、分页并阅读原文。缺失目录的结果不提供 Resume，新建任务也保持不可用；**Back to project results** 返回原查询、分页和来源行。

## 4. 准备好后再继续任务

阅读后先用 **Back to search** 返回结果，再点击 **Continue this conversation**。它使用 **Current Codex settings** 续接原来的原生 thread；**这一步需要保存的项目目录仍然存在**。缓存活动的 **Open matching activity** 使用原有 Desk 绑定和 profile。

如果只是想打开近期任务，首页 **Your recent Codex work** 中的 **Resume conversation** 可直接续接。按指定目录查找时，用 **Open a project** → **Project folder** → **Find existing sessions** → **Resume this conversation**，首次保持 **Current Codex settings**。

在任务框写下一步，选择 **Work — native tools and edits** 或 **Plan — clarify before execution**。等 **Draft saved locally** 出现，或点击 **Save as follow-up** 保存到当前会话的准备列表。准备完成后才点击 **Run task**，或在 **Prepared follow-ups** 中点击 **Send next**。

## 5. 关闭后回来

- **只关闭页面：** 终端和后台任务继续运行。在同一浏览器重新打开终端打印的完整 URL，会恢复上次打开的会话及草稿；也可在侧栏选择已保存的会话。
- **停止 Desk：** 在启动终端按 **Ctrl+C**，停止 Desk 管理的 app-server 和原生任务。再次运行 README 中同一条 uvx 命令，或从原虚拟环境启动 `codex-desk`。保持原来的 `--codex-home`、`--state-dir`、`--codex` 和 `--port` 参数，然后打开此次终端新打印的完整 URL。每次启动的浏览器访问片段不同，本地数据库保持原有记录。需要更新 uvx 缓存时，使用第 1 节的一次性更新命令。
- **检查准备是否恢复：** 选中同一会话，核对任务文字、Work／Plan 模式和 **Prepared follow-ups**。草稿和后续任务保存在本地，不会因重启自动发送。

本地记录默认位于 `~/.local/state/codex-desk/desk.sqlite3`。同一 state directory 保留会话绑定、索引缓存和准备内容；浏览器记住上次选中的会话。换浏览器时，在侧栏重新选择它。

### 不打开原生任务，也能检查和复用准备内容

首页或侧栏 **Prepared work** 按项目显示已保存的草稿和后续任务。点击 **Review draft and follow-ups** 阅读、复制或修改该会话的准备内容，目录已删除时仍可只读查看。后续任务的 **Use in this session draft** 先展示原指令，再用 **Append to draft** 或 **Replace draft text** 明确放入同一会话草稿；源后续任务及顺序不变。

**Save draft locally** 只保存草稿；**Save draft and open** 在保存成功后打开该会话，并显示刚审核的原文及 Work／Plan 模式，随后才由你决定是否运行。保存期间有更新的编辑、切换阅读或冲突时，会保留编辑而不继续打开。打开失败后可用 **Open conversation** 重试已保存的草稿，或继续本地检查。

已有任务打开时，**Recent work** 提供只读历史入口；**Return to selected work** 返回原任务，保留当前 Plan、草稿和后续任务。

## 6. 分享结果或求助

[分享真实任务结果或求助](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml)，填写三项必填信息：**The task you want to complete**、**Step reached** 和 **Result or first blocked step**。说明有用的原始证据、它改变或避免的检查，或第一个卡住的控件及状态。读到有用的原始证据就可以完成任务，无需继续会话；如果后来因真实任务主动返回，也可说明复用了什么。

**Operating system (optional)**、**Native Codex version (optional)** 和 **Expected result (optional)** 都是可选项。版本使用启动 Desk 的同一终端中的原生可执行文件版本输出或实际错误：独立 CLI 使用 `codex --version`；使用 `--codex` 时，按 [macOS](find-desktop-answer.macos.md) 或 [Windows](find-desktop-answer.windows.md) 指南对所选可执行文件运行版本检查。只试样例或尚未安装时，可选择 **Browser sample only** 或 **Before installing**，版本和系统可留空。[浏览器样例反馈表单](https://github.com/blucca/codex-desk/issues/new?template=browser-preview.yml) 用于记录样例结果。

**Steps and controls used**、**Context for this step**、**Codex Desk version** 和 **Short error text** 是可选项。复现可以用中性示例或搜索词长度，附简短的状态／错误文字即可。

| 症状 | 可复现路径与可选信息 |
| --- | --- |
| 正文搜索没有结果 | Find → Index → All indexed projects → Search；注明索引数量、搜索词长度和所选范围 |
| 匹配结果无法阅读 | 注明从正文结果还是标题列表点击 Read；记录 Retry read 后的实际状态 |
| 删除目录后无法继续 | 区分 Read original conversation 与 Continue this conversation；注明目录是否仍存在 |
| 返回后没有草稿 | 先等 Draft saved locally → 关闭／重启 → 选择同一会话；注明浏览器、state directory 和启动参数是否改变 |

[完整工作流：profile、审批、交接、归档和后续任务](workbench.md)（英文） · [英文答案查找指南与缓存范围](find-past-answer.md)

## 直接审阅当前会话的原文

在已选任务的顶部点击 **Read original conversation**，或从任务活动区域按 F3。原文从最新一页打开；Find 能检索全部可读原文，包括其他页和长工具输出。原文内 F3／Shift+F3 跳到下一处／上一处命中。任务输入框里的 F3 不触发这个入口。

**Refresh original** 只重新读取同一个原生会话，不运行任务。加载和失败时保留上次成功读取的内容；当前查询、已知条目和文本窗口保持原位。修改或取消过的 Find 不会被自动重新提交。返回任务保留未发送的 Work／Plan 草稿和排队指令；项目目录缺失或续接失败时，有保存的原生会话标识仍可读取原文。关闭原文后本次阅读视图结束。

## 从另一个任务审阅未确认的 Run 请求

在侧栏选择 **Prepared work**，再选择 **Review task request**。这里显示原始捕获的 Work/Plan 指令、原目标、当前目标和请求状态；不会打开原生任务，也不会改动当前任务或其他未保存草稿。

核实原任务是否启动后，选择 **It started — record accepted** 或 **It did not start — record rejected**，只记录该原始请求。**Refresh request** 重新读取同一个请求，**Return to Prepared work** 返回原审阅入口。原生目录或会话绑定改变时，恢复原绑定后才能记录结果。

### 找回未确认任务的原始指令

在 **Search saved content** 输入记得的原句，也能找到当前未确认的 Work/Plan 任务请求；即使已清空原草稿和队列，捕获的指令仍可检索。选择 **Review captured request** 查看精确原文和请求 ID，使用 **Read original conversation** 检查它所捕获的原会话。

**Return to results** 保留查询、项目范围、结果页和位置，不切换当前任务或覆盖独立的 Prepared 编辑器。明确记录是否已开始后，选择 **Search** 更新同一结果页；已解决请求不再列入未确认请求的检索。
