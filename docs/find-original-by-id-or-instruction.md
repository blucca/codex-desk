# Find the original from an ID or remembered instruction

[English](#english) · [中文](#中文)

## English

### Choose the shortest entrance

For a known conversation in your terminal, use `codex resume <SESSION_ID>` and
native transcript **Find** (default **F3**). Use Desk when you want to read that
original while keeping another task's draft open, or save a reviewed quote there.
[Native workflow reference](choose-history-workflow.md#find-evidence-in-a-known-conversation-without-desk).

| What you have | Desk entrance |
| --- | --- |
| A native thread ID in notes or a source reference | **Browse all conversations** → **Native conversation ID** → **Read original by ID**. Paste only the ID, such as the value after `Thread:` in a copied source reference. |
| Words from the conversation title | **Browse all conversations** → **Search conversation titles** → **Search titles** → **Read original conversation**. |
| Words from your instruction, with its original already open | **Read containing task** → **Jump to supplied user instruction** → **Find instructions**. This searches supplied user-message text throughout that loaded original. |
| Words from an answer, command or tool result | Across histories: **Search saved content** → **Index existing Codex history** → **Search**. Within an open original: **Find in this original conversation** → **Find**. |

ID and title reading use the selected native history directly. Instruction jump
needs an open original, not an index pass. Title search matches titles;
instruction jump matches user messages; original Find matches readable item text.
Literal punctuation is retained, with case and Unicode forms normalized. In the
original reader, **Copy native conversation ID** keeps that exact ID in your notes
for the next lookup.

After an original Find, **Show Find matches** lists up to 20 exact occurrences per
page within that loaded original. **Read match N** opens the selected turn/item
and native span, including one of two identical quotations in the same item.
**Read containing task** → **Return to original passage** keeps that occurrence,
Find and selection; **Return to Find matches** restores the same submitted query,
occurrence page and source row. Select another occurrence directly; F3/Shift+F3
then continues from its global ordinal. This is original-only navigation, separate
from instruction matching and cross-history content indexing.

### Revisit a native archived original

In **Browse all conversations**, choose **Archived conversations** under **Native history**,
then search its title and choose **Read original conversation**. The original stays
archived in Codex. This native catalog choice is separate from **Show archived**
for saved Desk tasks.

This browser remembers an original's supplied turn/item, displayed text window,
opened items and first visible literal character for its native home and
conversation. Close the reader, or reload Desk, then explicitly read the same
original again to return to that character in freshly read text. The remembered
literal character stays anchored through responsive reflow after a narrow/wide resize. Reload alone leaves the original closed. A saved quotation,
specified item or task-response target opens its requested passage instead and
keeps the ordinary reading checkpoint. The reader's Find query and selected text
are for the current reading visit; the remembered position contains view metadata.
For command output, the character position is relative to native output: a change
from `inProgress` with no exit code to `completed` / `0` can shorten the generated
header without moving your output passage. Held **Refresh original** and
**Read containing task** → Refresh → **Return to original passage** retain that
output character, Find and selection. Later deliberate Find/page/scroll input
keeps its newer reading intent; a width-only layout change does not replace the
prior output passage. Exact saved quotes keep their own native
source spans. [Try the command-header sample](../examples/browser-preview.md#keep-the-command-output-passage-when-its-status-header-changes).

### Follow newly supplied items in an original

1. Read the original normally by title or ID. The first successful fresh read in
   this browser establishes its supplied-item snapshot for that native home and
   conversation. It records what the source supplied, not which items you consumed.
2. When more items are supplied, deliberately reopen the same original or choose
   **Refresh original**. **New since previous fresh original read** compares the
   source's ordered turn/item identities with the previous successful fresh read.
   Editing text in an existing item does not make it a newly supplied item.
3. Choose **Read first newly supplied item** to inspect the exact first addition.
   It may be a user instruction or tool item before a later final answer. This
   navigates the already loaded original while B's Plan and both queues stay put.
4. **Return to original passage** restores the view, Find query and text selection
   you had immediately before that jump. Close and later reopen normally to use
   the remembered passage; explicit source targets still take priority.

Successful fresh reads advance this supplied-item snapshot; the control is not an
unread marker. **Read first new activity** instead follows recorded updates in a
saved task, including updates to earlier items, against its explicit review
frontier. **Mark displayed updates reviewed** belongs to that activity workflow;
reading new original items leaves it unchanged. Exact saved-reference/item/response
reads keep their own targets and do not replace the ordinary supplied-item snapshot.

Snapshot metadata stores the native-home/thread owner, item count and exact last
turn/item boundary. Reading metadata stores disclosures, windows and character
offsets, not original bodies, Find text or selections. Try the [five-item sample
and its four maintained checks](../examples/browser-preview.md#follow-newly-supplied-original-items).

### Start with your own history

[Install and launch Desk](../README.md#install-the-preview) using your existing
Codex executable and sign-in. Open the complete URL printed by that launch.
Native reading uses `--codex-home`, then `CODEX_HOME`, then `~/.codex` in the launch
environment. For a custom home, append `--codex-home /path/to/codex-home`.
Keep B's existing `--state-dir` and your original launch options when returning;
use a separate state directory for a separate Codex home.

**A** is the original evidence. **B** is the existing task you are preparing.
Leave B selected, write its next step, choose **Plan**, and wait for **Draft saved
locally**. Reading A keeps B's text, mode and ordered follow-ups in place. A's
project folder may be missing: its original history can still be read.

### ID → instruction → its own response → quote → return

1. Open **Browse all conversations** (or sidebar **Browse existing Codex
   sessions**). Paste A's ID in **Native conversation ID** and choose **Read
   original by ID**. This works independently of whether A appears in the title
   results. The reader identifies the supplied original.
2. Beside a readable original item, choose **Read containing task**. Enter your
   remembered prompt phrase in **Jump to supplied user instruction**, then
   **Find instructions**. Use **Next instruction matches** for later pages; each
   page holds up to 20 matching user-message items. Check the turn/item and snippet,
   then choose **Read task for this instruction**.
3. Choose **Read full instruction** to inspect its exact text and highlighted
   phrase. Choose **Return to task context**, then **Read this task response**.
   It uses that selected turn's last supplied final answer, otherwise its last
   readable assistant message. Read the reported phase and native turn status
   separately. **Copy full item text** includes the complete item, including text
   outside the displayed window.
4. In that response, use **Find in this original conversation** and **Next match**
   (F3) for the occurrence you need, checking its turn/item. Select the exact
   excerpt and choose **Review evidence for task**. Check A's IDs/quote beside B's existing Plan, then **Append
   to draft** once. B keeps its existing text and mode; queued instructions retain
   their order.
5. **Return to instruction matches** restores the query, page and source row;
   **Return to original passage** restores the original reading view. **Back to
   conversation ID** restores the ID field and title results. Close that browser
   to continue preparing B. In B, expand **Referenced originals in this draft**
   and choose **Read referenced original**: the saved occurrence opens in fresh
   original text. **Return to prepared task** restores B's editor selection and
   scroll.

**Refresh original** reads the same captured source/home again. To read a saved
reference after restarting Desk, retain its original Codex home and B's state
directory, and open the newly printed launch URL.

### Rehearse with the maintained sample

Build the [browser sample](../examples/browser-preview.md) to use synthetic
histories and browser-local preparation. Keep a sample task's existing Plan
selected as B. Use ID `sample-child-thread`, instruction phrase
`reported retry result`, then find the response quote
`Child decisive evidence — café🙂 项目 exact source.`. Choose the second occurrence
with **Next match**, review/append it and reopen the saved reference. The sample
child's project folder is absent. The installed workflow uses your own native
IDs, original text and local SQLite preparation.

## 中文

### 按手上已有的线索选择入口

只需在终端找回已知会话中的文字时，用 `codex resume <SESSION_ID>`，再用原生
transcript **Find**（默认 **F3**）。需要同时保留另一个任务的草稿，或把原文引句
保存到该任务时，再使用 Desk。[原生查找步骤](choose-history-workflow.md#find-evidence-in-a-known-conversation-without-desk)。

| 手上的线索 | Desk 入口 |
| --- | --- |
| 笔记或来源引用中的原生 thread ID | **Browse all conversations** → **Native conversation ID** → **Read original by ID**。只粘贴 ID，例如来源引用中 `Thread:` 后的值。 |
| 会话标题中的文字 | **Browse all conversations** → **Search conversation titles** → **Search titles** → **Read original conversation**。 |
| 记得自己输入的指令，且原会话已打开 | **Read containing task** → **Jump to supplied user instruction** → **Find instructions**，查找本次原文提供的全部用户消息。 |
| 答案、命令或工具结果中的文字 | 跨会话用 **Search saved content** → **Index existing Codex history** → **Search**；已打开的原文用 **Find in this original conversation** → **Find**。 |

ID／标题入口直接读取当前原生历史；指令跳转先打开原会话，无需先做索引。
标题搜索匹配标题，指令跳转匹配用户消息，原文 Find 匹配可读内容项。搜索保留
字面标点，忽略大小写并规范化 Unicode。原文查看器中的 **Copy native conversation ID**
复制当前原会话的准确 ID，便于保存到笔记中下次查找。

原文 Find 后用 **Show Find matches** 查看当前已加载原会话中的准确出现位置，
每页最多 20 处。**Read match N** 直接打开所选 turn／item 和原文范围，同一项中
两次相同引句也按各自位置区分。**Read containing task** → **Return to original
passage** 保留那次出现、Find 和选区；**Return to Find matches** 返回同一已提交
查询、出现位置页和来源行。直接选另一处后，F3／Shift+F3 从所选全局序号继续。
这是当前原文内部的导航，与用户指令匹配和跨会话正文索引分开。

### 回看原生已归档会话

在 **Browse all conversations** 的 **Native history** 中选 **Archived conversations**，搜索标题后
选择 **Read original conversation**。会话仍保持 Codex 原生归档状态；这个目录
选择与保存 Desk 任务的 **Show archived** 分开。

此浏览器按原生 home／会话记住实际 turn／item、文本窗口、展开状态和首个可见
文字的位置。关闭查看器或刷新 Desk 后，主动重新读取同一原会话，就在新读取的
原文中回到那个实际字符；窄屏／宽屏切换后仍按字符定位。刷新页面本身不读取
原文。保存引句、指定内容项或 task response 入口优先打开自己的准确段落，保留
普通阅读位置。Find 查询和文字选区属于本次阅读；记住的是阅读视图元数据。
命令输出按原生 output 内的字符位置恢复：状态从 `inProgress`／无退出码变为
`completed`／`0` 时，生成的状态头长度可能变化，但相同输出中的阅读字符保持
原位。等待中的 **Refresh original**，以及 **Read containing task** → Refresh →
**Return to original passage**，也保留输出字符、Find 与选区；保存引句仍按自己的
准确原生来源范围打开。等待期间明确的新 Find／翻页／滚动意图仍优先；仅布局
宽度变化不会替换先前输出段落。[命令状态头示例](../examples/browser-preview.md#keep-the-command-output-passage-when-its-status-header-changes)。

### 跟进原会话新提供的内容项

1. 按标题或 ID 普通读取原会话。此浏览器在该原生 home／会话首次成功读取
   新鲜原文时建立「已提供内容项」快照，记录来源提供了什么，而非你读完了什么。
2. 后来有新内容时，主动重新打开同一原文，或点 **Refresh original**。
   **New since previous fresh original read** 按原生 turn／item 的顺序和身份，
   与上一次成功的新鲜读取比较；已有内容项的文字修改不计为新提供的内容项。
3. **Read first newly supplied item** 打开准确的第一项新增内容，可能是用户指令
   或工具项，而不是后面某回合的 final answer。它在已加载的原文中跳转，B 的
   Plan 和两组待发队列保持原样。
4. **Return to original passage** 恢复跳转前的阅读视图、Find 查询和文字选区。
   关闭后再普通重读会恢复记住的段落；明确指定的来源入口仍优先定位自己的内容。

每次成功的新鲜读取会推进已提供内容项快照，这不是未读标记。**Read first new
activity** 则按保存任务中记录的更新与明确审阅边界比较，也包括较早内容项的
更新；**Mark displayed updates reviewed** 属于该活动流程。阅读原文新增内容
不改变活动审阅边界。保存引句／指定内容项／回答的准确入口也不会替换普通的
已提供内容项快照。

快照只保存原生 home／thread、内容项数量和末项的准确 turn／item 边界；阅读
元数据保存展开状态、文本窗口和字符位置，不保存原文正文、Find 文字或选区。
可用[五项合成新增内容及四组维护检查](../examples/browser-preview.md#follow-newly-supplied-original-items)练习。

### 连接自己的历史，保留当前 B

按 [安装与启动步骤](../README.md#install-the-preview)使用已有 Codex 可执行文件
和登录，打开此次终端打印的完整 URL。原生读取依次使用 `--codex-home`、
`CODEX_HOME`、启动环境中的 `~/.codex`；自定义目录用
`--codex-home /你的/codex-home`。返回原有准备内容时保留 B 的 `--state-dir`
和原启动参数；另一套 Codex home 使用独立的 state directory。

A 是要阅读的原始证据，B 是正在准备的已有任务。保持 B 选中，写好下一步，
选择 **Plan**，等待 **Draft saved locally**。阅读 A 时，B 的文字、模式和后续
指令顺序保持原样；A 的项目目录已删除时仍可阅读其原生历史。

### ID → 用户指令 → 同一回合的回答 → 引句 → 返回

1. 打开 **Browse all conversations**（侧栏为 **Browse existing Codex sessions**），
   在 **Native conversation ID** 粘贴 A 的 ID，点 **Read original by ID**。
   A 是否出现在标题结果中，不影响按 ID 阅读。
2. 在原文内容项旁点击 **Read containing task**。在 **Jump to supplied user
   instruction** 输入记得的指令短语，点 **Find instructions**。每页最多 20 个
   匹配的用户消息；用 **Next instruction matches** 翻页，核对 turn／item 和原文
   片段，再点 **Read task for this instruction**。
3. 用 **Read full instruction** 查看完整指令及高亮短语；**Return to task context**
   后点 **Read this task response**。它读取该回合最后提供的 final answer；没有
   final answer 时读取同回合最后一条可读 assistant 消息。分别核对原生回合状态和
   phase。**Copy full item text** 复制完整内容项，包括当前文字窗口之外的文字。
4. 在回答中用 **Find in this original conversation**，再用 **Next match**（F3）
   到所需的那次出现，核对 turn／item。选中准确引句，点 **Review evidence for task**，核对 A 的
   ID／引句和 B 的已有 Plan，再点一次 **Append to draft**。B 的原文字、模式和
   已有后续指令的顺序保持原样。
5. **Return to instruction matches** 返回同一查询、页和来源行；**Return to original
   passage** 恢复原来的阅读位置；**Back to conversation ID** 返回 ID 输入框和
   标题结果。关闭列表后继续准备 B。展开 B 的 **Referenced originals in this draft**，
   点 **Read referenced original**，在新读取的原文中查看已保存的那次引句；
   **Return to prepared task** 恢复 B 编辑器的选区和滚动位置。

**Refresh original** 再次读取同一个已捕获的来源／home。重启后阅读已保存引用时，
保持原 Codex home 和 B 的 state directory，打开此次新打印的启动 URL。

### 用维护中的合成示例练习

按 [示例构建步骤](../examples/browser-preview.md)打开浏览器示例，保持已有示例
任务的 Plan 选中作为 B。使用 ID `sample-child-thread`，指令短语
`reported retry result`，再查找回答中的
`Child decisive evidence — café🙂 项目 exact source.`，用 **Next match** 到第二次
出现，审阅／追加引句并重新打开保存的引用。这个合成 child 的项目目录不存在。
示例历史与准备内容在浏览器中；安装后的流程读取自己的原生 ID／原文，准备
内容保存在本地 SQLite。
