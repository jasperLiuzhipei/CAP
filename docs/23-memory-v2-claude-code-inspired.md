# Memory v2: Claude Code Inspired Design

## Claude Code 的核心思路

`cc-haha-main` 的 memory 设计有几个很值得借鉴的点：

1. **类型封闭**
   memory 不是随便写日志，而是限制为少数类型。Claude Code 里是 `user`、`feedback`、`project`、`reference`。这样可以让模型知道每条 memory 应该怎么保存、什么时候使用、什么时候不要保存。

2. **索引和内容分离**
   `MEMORY.md` 更像一个索引入口，不鼓励把所有长内容直接堆进去。详细内容放到单独 memory 文件中，索引只保留短 hook。这样 prompt 不会无限膨胀。

3. **只保存不可从当前代码推导的信息**
   代码结构、函数位置、git 历史、架构快照通常不应该长期记忆，因为这些可以通过读当前 repo 或 git 得到。长期 memory 更适合保存项目背景、用户偏好、团队约束、外部系统入口、非显而易见的决策原因。

4. **检索式召回**
   Claude Code 会扫描 memory 文件 frontmatter，先拿文件名、description、type 做 relevance selection，再只读取少量相关 memory。它不是把所有 memory 都塞进上下文。

5. **陈旧和冲突意识**
   memory 是 point-in-time observation。凡是 memory 里提到文件、函数、flag、命令，都需要在行动前用当前 repo 验证。新旧 memory 冲突时，要更新或删除旧 memory，而不是盲目并存。

6. **压缩而不是无限追加**
   对长期会话或大量历史，Claude Code 有 compact / summary / daily log 的思路。原始历史不应该永远全部注入，应该沉淀为摘要或索引。

## 我们的 Memory v2 映射

当前平台先实现本地文件型 Memory v2：

```text
.copilot/
  memory.md      # 人类可读索引，兼容旧入口
  memory.json    # 结构化 source of truth
```

`memory.md` 仍然存在，是为了方便人读、兼容已有 CLI/API 配置。
真正用于读写、检索、冲突处理的是 `memory.json`。

## Memory v2 Schema

当前结构分为四块：

| 区域 | 用途 |
| --- | --- |
| `project_facts` | 项目事实、背景、约束、外部原因 |
| `code_preferences` | 用户或团队希望 Copilot 遵循的代码/沟通偏好 |
| `run_history` | 历史 run 摘要、改动文件、验证结果 |
| `conflicts` | 同标题 memory 内容变化时的冲突记录 |

每条 project fact / code preference 都包含：

- `id`
- `category`
- `title`
- `content`
- `source_run_id`
- `confidence`
- `status`: `active`、`superseded`、`stale`
- `tags`
- `why`
- `how_to_apply`
- `created_at`
- `updated_at`

## 读路径

Phase-one prompt 现在调用：

```python
load_memory_text(repo, memory_path, query=config.task)
```

这意味着 Memory v2 会根据当前任务做轻量关键词检索，只注入：

- 与任务匹配的 active project facts / code preferences
- 最近 5 条 run history
- 最近 conflict 提示
- compacted run summary

如果 `memory.json` 不存在，但旧 `memory.md` 存在，会继续按旧 markdown 方式读取，保持兼容。

## 写路径

run 完成后：

```python
append_run_memory(report, memory_path)
```

会写入结构化 `run_history`，然后重新生成 `memory.md` 索引。

未来 Memory Curator 可以调用：

```python
upsert_memory_record(
    repo,
    category="project_fact",
    title="Test command",
    content="Run tests with python -m pytest tests.",
    source_run_id="run_xxx",
)
```

## 冲突处理

当同一 category 下出现相同 normalized title、但 content 不同：

1. 旧 record 标记为 `superseded`。
2. 新 record 保持 `active`。
3. `conflicts` 写入 old -> new 的来源链。
4. prompt 中提示 newer memory wins，但仍要求以当前 repo 为准。

这比简单覆盖更安全，因为未来可以审计“为什么这条记忆变了”。

## 压缩策略

`run_history` 默认保留最近 20 条。
超过后会把更旧 run 压缩到 `compacted_run_summary`。

这对应 Claude Code 的 compact 思想：历史可以保留，但不应该无限增长并全部进入 prompt。

## 暂未移植

这次没有移植以下复杂能力：

- LLM relevance selector。
- 向量检索。
- private/team memory 同步。
- daily log + nightly distillation。
- memory Web UI editor。
- 自动从对话中抽取 project facts / preferences。

这些适合作为后续 Memory Curator 和 Web UI 的迭代。
