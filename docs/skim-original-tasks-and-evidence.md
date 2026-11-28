# Skim an original by task, then inspect its own evidence

[English](#english) · [中文](#中文)

## English

When you remember the work but not a search phrase, read its original by native
ID or title and choose **Task overview**. This overview uses the supplied tasks
from that loaded original.

### Pick the exact task

- Each page contains up to **20 supplied tasks**, in native order. A row gives
  its native turn ID, reported status, supplied instruction previews and its own
  assistant response/phase. **Next tasks** and **Previous tasks** browse the chain.
- Choose **Read task** for its complete supplied context, or **Read task
  response** for its selected actual assistant item. A supplied `final_answer`
  wins within its own turn; otherwise the last supplied assistant message keeps
  its reported phase.
- **Return to task overview** restores the same page, reading scroll and chosen
  control. Empty/interrupted tasks, missing instructions and tasks without a
  readable assistant response remain their own rows.

### Read that task’s tools and results

In its context choose **Read this task’s evidence**. The list contains that
captured turn’s supplied native items, up to **20 items per page**. Commands,
messages, file changes, MCP/tool results and unsupported items retain their
native order and identity. Use **Next task evidence** to reach later items.

If the supplied list contains only messages, **Read this task response** still
reads that task’s answer. Use its reported decision when that is what you need;
keep any present-day check that depends on an absent command/tool result.
[First-task steps for message-only originals](find-past-answer.md#if-the-original-supplies-messages-but-no-command-result).

Choose **Read full original item** to use the existing original renderer and
long-text windows. **Copy full item text** includes the full projection rather
than the visible window. **Copy source reference** retains the exact thread,
turn and item. Select a literal excerpt and choose **Review evidence for task**;
append once when you want to save it into the existing unsent draft, or choose
**Return without appending** to keep the draft unchanged.

| Find scope | Supplied text searched |
| --- | --- |
| **This task’s supplied evidence only** | The selected native turn’s readable items |
| **Whole original conversation** | Every supplied readable task/item in the loaded original |

Find retains literal source spans while normalizing case and Unicode for
matching. **Show Find matches** lists the occurrences in the chosen scope;
choose an exact occurrence directly. F3/Shift+F3 continues from that ordinal.
Changing the scope starts a new Find intent; submit the phrase for that scope.

### Keep the original and your current preparation

Use **Return to task evidence** for the item list, **Return to task overview** for
the supplied task chain, and **Return to original passage** for the passage you
started from. The original Find ordinal, text window, disclosure and selected
Range return with it. Close the original to return to your current editor,
draft mode and paused follow-ups. Browsing the loaded source needs no extra
native original read.

**Refresh original** explicitly reads a fresh snapshot. The overview and evidence
lists then reflect its supplied tasks/items; an unavailable captured identity
stays unavailable rather than choosing a neighbouring task’s same text.

[Rehearse the synthetic task review in the browser sample](../examples/browser-preview.md#skim-supplied-tasks-and-inspect-their-own-evidence).

## 中文

记得以前做过的工作，但想不起搜索词时，可以按原生会话 ID 或标题读原文，再选
**Task overview**（任务概览）。概览使用这次已经读到的原生原文。

### 选择准确的任务

- 每页最多 **20 个原生任务**，保持原生顺序。每行显示原生 turn ID、报告的状态、
  已提供的指令预览，以及这个任务自己的助手回复和 phase。
  **Next tasks / Previous tasks** 用于浏览任务链。
- **Read task** 阅读完整的任务上下文；**Read task response** 阅读该任务选中的真实
  助手条目。同一 turn 内优先选 `final_answer`；没有时使用最后一条已提供的助手消息，
  保留原来报告的 phase。
- **Return to task overview** 返回同一概览页、滚动位置和所选控件。
  空任务、中断任务、未提供指令或没有可读助手回复的任务仍保留自己的行。

### 阅读这个任务自己的工具证据

在任务上下文选择 **Read this task’s evidence**。列表仅包含所选 turn 的已提供原生
条目，每页最多 **20 个**。命令、消息、文件改动、MCP/工具结果和不支持的条目都保持
原生顺序及身份。**Next task evidence** 可以继续到后面的条目。

如果列表只提供消息，**Read this task response** 仍可阅读该任务自己的回答。
所需的是回答中已报告的决策时，可据此准备下一步；依赖未提供的命令／工具结果的检查
继续保留在今天的任务中。[首次任务步骤](first-project.zh-CN.md#首次任务读出决策再检查该任务自己的结果)。

选择 **Read full original item**，使用原有全文渲染和长文本窗口。
**Copy full item text** 复制完整投影；**Copy source reference** 保留准确的 thread、
turn 和 item。选中原文片段后选择 **Review evidence for task**：需要保存时显式追加一次，
只检查证据时选择 **Return without appending**，保持当前未发送草稿不变。

| Find 范围 | 搜索的已提供文本 |
| --- | --- |
| **This task’s supplied evidence only** | 所选原生 turn 的可读条目 |
| **Whole original conversation** | 已读原文中所有任务和条目的可读文本 |

Find 对大小写和 Unicode 做匹配规范化，但结果保留原文的准确跨度。
**Show Find matches** 显示当前范围的命中位置；可以直接选择准确的重复位置，
F3/Shift+F3 从该全局序号继续。切换范围后，重新提交词语以搜索该范围。

### 返回原来读的位置和当前准备

**Return to task evidence** 返回条目列表；**Return to task overview** 返回任务链；
**Return to original passage** 返回最初读的原文片段，并恢复 Find 序号、文本窗口、
展开状态和选中的 Range。关闭原文后，回到当前编辑器、草稿模式和暂停的后续指令。
浏览已经读到的原文，不再请求新的原生原文。

**Refresh original** 显式读取新快照，概览和证据列表随其实际提供的任务/条目更新。
捕获的身份缺失时会显示当前可用性，保留原来的身份。

[在浏览器示例中演练任务概览和任务证据](../examples/browser-preview.md#skim-supplied-tasks-and-inspect-their-own-evidence)。
