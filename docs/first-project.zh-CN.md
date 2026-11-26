# Codex Desk：找回旧答案，先阅读，再继续任务

记得答案中的一句话，却忘了会话标题？用已有的 Codex CLI 和登录，索引本机历史、查找文字并阅读原会话；准备好后再续接同一个任务。界面目前使用英文，下面保留实际按钮名称。

[20 秒示例：索引 → 查找答案 → 阅读原会话](find-answer.gif)（合成的结账项目历史）

## 1. 安装并启动

在准备启动 Desk 的终端确认 `codex --version` 可用。按 [README 维护中的安装步骤](../README.md#install-the-preview)运行单条 uvx 命令；使用 Python 安装时，展开对应系统的虚拟环境步骤，需要 Python 3.11+。

保持终端运行，打开它打印的地址，默认是 **`http://127.0.0.1:8787`**。 如果提示地址已占用，原 Desk 终端仍运行时直接重新打开该地址；需要换端口时，在启动命令后加 `--port 8788`。端口占用不会创建或修改 Desk 记录。如果 Codex 历史位于其他目录，在启动命令后加 `--codex-home /你的目录`。Windows 与 WSL 使用各自启动环境中可访问的 Codex home 和项目路径。

## 2. 按答案中的文字查找

1. 首页点击 **Find a decision in past work**；已有会话打开时，点击侧栏 **Search saved content**。
2. 点击 **Index existing Codex history**，明确读取最近更新的最多 **200 个原生会话**，包括尚未在 Desk 打开过的历史。等状态显示完成，核对 seen／indexed／unchanged／failed 数量。索引只读取历史并保存本地缓存，不创建会话绑定或发送任务。
3. 先保持 **All indexed projects**。在 **Saved content query** 输入旧答案、命令输出或工具结果中实际出现的 **2–200 个字符**，再点击 **Search** 或按 Enter。索引进行中也可以提交查询；明确启动的索引完成后，仍在当前搜索对话框中、未修改的已提交查询会自动刷新一次。搜索按字面文字匹配，忽略大小写并规范化 Unicode。修改文字或范围后，点击 **Search** 提交修改。
4. 核对结果中的会话、项目目录和匹配片段。需要缩小范围时，选择 **Project folder (optional)**，再点 **Search**。

**Index coverage and text limits** 显示实际缓存范围和缩短／省略的条目。**Index existing history again** 刷新最近 200 个会话并跳过未变化的快照，不会自动进入更旧历史。**Cancel indexing** 保留已缓存的内容；关闭搜索对话框后，正在进行的索引仍会继续。失败或取消后用 **Retry** 重试。

索引完成时会保留未提交的修改、正在阅读的原会话、结果焦点和导航选择。关闭搜索对话框或正在查看已有结果时，返回后用 **Search** 更新匹配。仍在等待响应的已提交查询会先完成，再执行一次新查询；新提交的查询优先于旧响应。

## 3. 只读原会话

在原生历史结果或带有原 thread 的缓存活动结果中，点击 **Read original conversation**。查看器定位原 turn／item，并高亮匹配文字；当前打开的任务和草稿保持不变。

**项目目录已删除，也能阅读原历史。** 阅读不导入、不续接 thread。点击 **Back to search** 或 **Close** 返回原查询和结果。

长会话每页显示 **40 个条目**，用 **Previous items**／**Next items** 换页。长输出用 **Earlier text**／**Later text** 阅读其他文字窗口，每个窗口最多 **20,000 个字符**。原匹配项已变化时，查看器显示实际定位状态；读取失败用 **Retry read** 重试。

### 已知标题，或会话不在近期索引里

首页点击 **Browse all conversations**，或侧栏 **Browse existing Codex sessions**。输入标题文字，点击 **Search titles**，需要时用 **Load more**。在该行直接点击 **Read original conversation**，无需先续接，也不要求原目录存在。返回后保留标题查询和已加载列表。

标题搜索不搜索正文。若要把更旧会话的正文加入内容搜索，可在目录存在时明确续接它；打开后的可读活动会缓存到 Desk。

## 4. 准备好后再继续任务

阅读后先用 **Back to search** 返回结果，再点击 **Continue this conversation**。它使用 **Current Codex settings** 续接原来的原生 thread；**这一步需要保存的项目目录仍然存在**。缓存活动的 **Open matching activity** 使用原有 Desk 绑定和 profile。

如果只是想打开近期任务，首页 **Your recent Codex work** 中的 **Resume conversation** 可直接续接。按指定目录查找时，用 **Open a project** → **Project folder** → **Find existing sessions** → **Resume this conversation**，首次保持 **Current Codex settings**。

在任务框写下一步，选择 **Work — native tools and edits** 或 **Plan — clarify before execution**。等 **Draft saved locally** 出现，或点击 **Save as follow-up** 保存到当前会话的准备列表。准备完成后才点击 **Run task**，或在 **Prepared follow-ups** 中点击 **Send next**。

## 5. 关闭后回来

- **只关闭页面：** 终端和后台任务继续运行。在同一浏览器重新打开终端打印的 URL，会恢复上次打开的会话及草稿；也可在侧栏选择已保存的会话。
- **停止 Desk：** 在启动终端按 **Ctrl+C**，停止 Desk 管理的 app-server 和原生任务。再次运行 README 中同一条 uvx 命令，或从原虚拟环境启动 `codex-desk`。保持原来的 `--codex-home`、`--state-dir` 和 `--codex` 参数。
- **检查准备是否恢复：** 选中同一会话，核对任务文字、Work／Plan 模式和 **Prepared follow-ups**。草稿和后续任务保存在本地，不会因重启自动发送。

本地记录默认位于 `~/.local/state/codex-desk/desk.sqlite3`。同一 state directory 保留会话绑定、索引缓存和准备内容；浏览器记住上次选中的会话。换浏览器时，在侧栏重新选择它。

## 6. 卡在哪一步？

[填写任务求助表单](https://github.com/blucca/codex-desk/issues/new?template=task-help.yml)，说明 **Operating system**、**Codex CLI version**、**The task you want to complete**、**Step reached**、**Expected result** 和 **Actual result**。CLI 版本使用启动 Desk 的同一终端中的 `codex --version` 输出；命令不可用时填写实际错误。

**Steps and controls used**、**Context for this step**、**Codex Desk version** 和 **Short error text** 是可选项。复现可以用中性示例或搜索词长度，附简短的状态／错误文字即可。

| 症状 | 可复现路径与可选信息 |
| --- | --- |
| 正文搜索没有结果 | Find → Index → All indexed projects → Search；注明索引数量、搜索词长度和所选范围 |
| 匹配结果无法阅读 | 注明从正文结果还是标题列表点击 Read；记录 Retry read 后的实际状态 |
| 删除目录后无法继续 | 区分 Read original conversation 与 Continue this conversation；注明目录是否仍存在 |
| 返回后没有草稿 | 先等 Draft saved locally → 关闭／重启 → 选择同一会话；注明浏览器、state directory 和启动参数是否改变 |

[完整工作流：profile、审批、交接、归档和后续任务](workbench.md)（英文） · [英文答案查找指南与缓存范围](find-past-answer.md)
