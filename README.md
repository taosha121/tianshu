# 灵机一动 (lingjiyidong)

灵光乍现，代码自成。一个从零手写的 AI 代码 Agent，不依赖 LangChain 等框架。

## 安装

```bash
pip install lingjiyidong
```

## 使用

需要先设置 Anthropic API Key：

```bash
export ANTHROPIC_API_KEY=your_key
```

然后直接启动：

```bash
lj
```

## 功能

- **对话模式**：直接与 Agent 对话，支持多轮上下文
- **任务规划模式**：输入 `/plan <目标>`，Agent 自动拆解任务并逐步执行
- **工具调用**：读写文件、执行命令、搜索代码、抓取网页等
- **长期记忆**：自动保存重要信息，下次启动时加载
- **上下文压缩**：长对话自动压缩，不会撑爆 context window

## 内置工具

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件内容 |
| `write_file` | 创建或覆盖写入文件 |
| `edit_file` | 精准替换文件中的一段内容 |
| `create_directory` | 创建目录 |
| `list_files` | 列举目录文件 |
| `grep_files` | 全文搜索代码和文本 |
| `bash` | 执行 shell 命令 |
| `web_search` | 网络搜索（需配置 `TAVILY_API_KEY`） |
| `web_fetch` | 抓取网页内容 |
| `save_memory` | 保存信息到长期记忆 |

## 技术栈

- Python 3.11+
- Claude API（Anthropic SDK）
- 无框架，手写核心循环
