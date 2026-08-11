# 工具系统设计

## 为什么需要工具

大模型本身只能处理文本，没有感知和操作外部世界的能力。要让 Agent 真正能写代码、读文件、执行命令，就必须给它配备工具。

Anthropic 的 tool use API 提供了标准协议：开发者在请求里声明工具的名称、描述和参数 schema，模型决定是否调用、调用哪个、传什么参数，开发者执行后把结果返回，模型继续推理。这个项目里的工具集就是围绕"代码 Agent 需要做哪些事"来设计的。

---

## 工具清单与设计思路

### 文件操作类

**`read_file`**
读取本地文件内容。支持 `start_line` / `end_line` 只读指定行范围，避免大文件一次性读入占满上下文。

**`write_file`**
创建或覆盖写入文件。父目录不存在时自动创建，减少 Agent 需要单独创建目录的步骤。

**`edit_file`**
精准替换文件中的一段内容（`old_string` → `new_string`）。`old_string` 必须在文件中唯一存在，否则拒绝执行并提示。这个设计的核心是**避免重写整个文件**——只发送 diff，节省 token，也降低误操作风险。

**`create_directory`**
创建目录，支持递归多级创建。

**`list_files`**
列举目录下的文件，支持 glob 过滤（如 `**/*.py`）。

### 代码导航类

**`get_outline`**
返回一个文件里所有函数和类的签名与行号，不含函数体。对应"先看目录再翻页"的阅读策略——Agent 先用 `get_outline` 定位感兴趣的函数，再用 `read_file` 只读那几行，比直接读整个文件省大量 token。

支持 Python（`def` / `async def` / `class`）和 JavaScript/TypeScript（函数声明、class、箭头函数、UI5 模式）。

**`find_symbol`**
在整个 repo 中搜索某个函数或类的定义位置，返回文件名和行号，等价于 IDE 里的"跳转到定义"。底层是 `grep -rn` 的正则搜索，对 Python 和 JS/TS 分别构造匹配模式。

### 执行类

**`bash`**
在 shell 里执行任意命令，返回 stdout 和 stderr。可用于运行测试、安装依赖、git 操作等。设有 `timeout` 参数（默认 30 秒）防止挂死。

**`grep_files`**
在目录中搜索匹配指定模式的文本，返回文件名和行号。相比 `bash` 直接跑 grep，这个工具封装了参数构造，对 Agent 来说描述更清晰。

### 网络类

**`web_search`**
调用 Tavily API 搜索网络，返回最多 5 条结果的摘要和链接。用于查文档、查 API 用法、查报错原因。

**`web_fetch`**
抓取指定 URL 的原始内容，用于阅读具体的文档页面或 GitHub issue。

### 记忆类

**`save_memory`**
将信息追加写入 `.agent/memory.md`。Agent 可以主动调用，把需要跨会话记住的内容持久化。下次启动时，`LongTermMemory` 自动加载并注入 system prompt。

---

## 工具的实现结构

每个工具是一个 `Tool` dataclass（定义在 [lingjiyidong/agent/tools/__init__.py](../lingjiyidong/agent/tools/__init__.py)）：

```python
@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., Any]

    def to_api_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
```

- `name`：工具名，模型调用时用这个名字
- `description`：**最关键的字段**，模型完全依靠这段文字决定什么时候用这个工具、怎么用
- `input_schema`：JSON Schema 格式，声明参数名、类型、是否必填
- `func`：实际执行逻辑的 Python 函数

---

## 工具注册：让模型知道有哪些工具

在 [lingjiyidong/agent/__init__.py](../lingjiyidong/agent/__init__.py) 顶部：

```python
_TOOL_SCHEMAS = [t.to_api_dict() for t in TOOLS]
```

启动时把所有工具的 `name` + `description` + `input_schema` 序列化成列表，每次调用 API 时通过 `tools=_TOOL_SCHEMAS` 传给模型：

```python
response = self.client.messages.create(
    model=self.model,
    max_tokens=8192,
    system=system,
    messages=self.history,
    tools=_TOOL_SCHEMAS,      # ← 工具声明
)
```

模型看到这份列表后，如果判断需要使用某个工具，会在响应的 `content` 里返回一个 `ToolUseBlock`，包含工具名和参数。Agent 从 `TOOL_MAP`（一个 `name → Tool` 的字典）里找到对应工具，调用 `tool.func(**block.input)` 执行，把结果作为 `tool_result` 追加回对话历史，触发下一轮推理。

新增一个工具只需要：写实现函数 → 构造 `Tool` 对象 → 加入 `TOOLS` 列表，无需修改 Agent 核心逻辑。
