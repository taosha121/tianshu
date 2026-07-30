import os

import anthropic
from dotenv import load_dotenv

from agent.memory import ContextManager, LongTermMemory
from agent.tools import TOOLS, TOOL_MAP

load_dotenv()

_TOOL_SCHEMAS = [t.to_api_dict() for t in TOOLS]
_MAX_ITERATIONS = 10
_SYSTEM_PROMPT = "You are a helpful assistant."


class Agent:
    def __init__(self, model: str = "anthropic--claude-4.5-sonnet"):
        self.client = anthropic.Anthropic(
            base_url="http://localhost:6655/anthropic",
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
        self.model = model
        self.history = []
        self.context = ContextManager()
        self.longterm = LongTermMemory()

    def chat(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        self.history = self.context.maybe_compress(self.history, self.client, self.model)

        system = _SYSTEM_PROMPT + self.longterm.system_addendum + self.context.system_addendum

        for _ in range(_MAX_ITERATIONS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=self.history,
                tools=_TOOL_SCHEMAS,
            )

            # response 结构：
            # Message(
            #   id='msg_...',
            #   role='assistant',
            #   stop_reason='end_turn' | 'tool_use',
            #   content=[
            #     TextBlock(type='text', text='...'),           # 普通回复
            #     ToolUseBlock(type='tool_use', id='toolu_bdrk_01WAuQA2mUDLFuFdtxZEgrAa', # 工具调用
            #                  name='calculator', input={'expression': '2+2'}),
            #   ],
            #   usage=Usage(input_tokens=..., output_tokens=...)
            # )
            self.history.append({"role": "assistant", "content": response.content})

            # stop_reason == 'end_turn'  → Claude 直接回答，无工具调用，退出循环
            # stop_reason == 'tool_use'  → Claude 要调用工具，继续循环
            if response.stop_reason != "tool_use":
                return response.content[0].text

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool = TOOL_MAP.get(block.name)
                result = tool.func(**block.input) if tool else f"未知工具: {block.name}"
                print(f"  [工具调用] {block.name}({block.input}) → {result}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            self.history.append({"role": "user", "content": tool_results})

        return "已达到最大迭代次数，未能完成任务。"
