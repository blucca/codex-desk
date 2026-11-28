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
