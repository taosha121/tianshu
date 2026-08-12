# 记忆系统设计

## 两种记忆的对比

Agent 有两类记忆，解决的是两个不同的问题：

| | 短期记忆（ContextManager） | 长期记忆（LongTermMemory） |
|---|---|---|
| 存储位置 | Python 对象，内存里 | `.agent/memory.md`，磁盘上 |
| 生命周期 | 进程运行期间 | 跨会话持久 |
| 内容 | 当前对话的完整历史 | Agent 主动写入的笔记 |
| 写入者 | 框架自动维护 | Agent 调用 `save_memory` 工具 |
| 读取时机 | 每次 API 调用都带上 | 每次构建 system prompt 时注入 |

---

## 短期记忆：ContextManager

实现在 [tianshu/agent/memory/context.py](../tianshu/agent/memory/context.py)。

管理的是 `self.history`——每轮对话追加的消息列表。每条消息是一个 `{"role": ..., "content": ...}` 字典，随每次 API 请求整体发给模型。

**问题：history 会无限增长。**

模型的 context window 是有上限的（这个项目用的模型上限约 200K token），而且 token 越多，API 调用越慢越贵。`ContextManager` 的职责就是在 history 撑到上限之前把它压缩掉。

### 压缩策略

```
每次 chat() 调用前检查：
  估算 history token 数
  如果 > max_tokens * compress_threshold（默认 80000 * 0.75 = 60000）：
    把 history[-4:] 以外的旧消息压缩成摘要
    用摘要替换旧消息，只保留最近 4 条
```

压缩本身是一次额外的 API 调用——让模型把旧对话总结成一段文字，存进 `_summary`。下次压缩时，已有摘要会并入新摘要（滚动摘要）。

```python
existing = f"已有摘要：\n{self._summary}\n\n" if self._summary else ""
prompt = f"{existing}请将以下对话压缩为简洁的摘要..."
```

摘要通过 `system_addendum` 属性注入到每次 API 调用的 system prompt 尾部：

```python
system = self._system_prompt + self.longterm.system_addendum + self.context.system_addendum
```

### token 估算

用字符数 / 1.5 粗估，不调用 token counting API，避免每轮多一次网络请求。中文字符占两个字节但通常对应 1-2 个 token，1.5 这个系数是个保守估计。

---

## 长期记忆：LongTermMemory

实现在 [tianshu/agent/memory/longterm.py](../tianshu/agent/memory/longterm.py)。

存储在工作目录的 `.agent/memory.md` 文件里，纯文本，Markdown 格式。

### 写入

只有 Agent 主动调用 `save_memory` 工具时才会写入：

```python
# tools/__init__.py 里的 save_memory 工具
def save_memory(content: str) -> str:
    memory.append(content)
    return "已保存到长期记忆"
```

`append()` 是追加写，不覆盖已有内容——每次调用在文件末尾加一段，历史笔记都保留。

### 读取

每次 `Agent.chat()` 构建 system prompt 时调用 `system_addendum`：

```python
@property
def system_addendum(self) -> str:
    content = self.load()
    if not content:
        return ""
    return f"\n\n--- 长期记忆 ---\n{content}\n--- 记忆结束 ---"
```

文件不存在时返回空字符串，不报错。文件一旦有内容，每次 API 调用都会把全部内容塞进 system prompt。

### 局限

长期记忆文件会随使用时间不断增大。目前没有过期机制或清理逻辑——如果 Agent 频繁调用 `save_memory`，`.agent/memory.md` 最终也会把 system prompt 撑满。

---

## system prompt 的拼接顺序

```python
system = self._system_prompt          # 工作目录、项目结构、工具说明
       + self.longterm.system_addendum # 长期记忆（如果有）
       + self.context.system_addendum  # 对话摘要（如果有）
```

三段都是字符串直接拼接，分隔符是各自的 `--- 标题 ---` 块。顺序有意义：项目上下文在前，记忆在后，摘要压后——模型倾向于更重视靠近末尾的内容。

---

## 两类记忆的协作

一次完整的对话流：

```
启动时：
  LongTermMemory.load()  →  上次会话留下的笔记注入 system prompt

对话中：
  每轮 chat()：
    ContextManager.maybe_compress()  →  history 太长时压缩
    API 调用带上完整 history         →  短期记忆发挥作用

Agent 认为值得记住时：
  调用 save_memory 工具              →  写入 .agent/memory.md

下次启动：
  LongTermMemory.load() 再次读取    →  上次写的内容仍然生效
```

短期记忆是"工作台"，存放当前任务的所有中间状态；长期记忆是"笔记本"，存放跨任务需要复用的结论。
