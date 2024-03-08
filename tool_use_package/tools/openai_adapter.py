
# openai tools in claude prompt out
from typing import Any

from prompt_constructors import construct_format_tool_for_claude_prompt

def openai_tools_adapter(tools: list[dict[str, Any]]) -> list[str]:
    return f"""
Here are the tools available:
<tools>
        + '\n'.join([tool.format_tool_for_claude() for tool in tools]) +
</tools>
"""

def openai_tool_adapter(tool: dict[str, Any]) -> str:
    return construct_format_tool_for_claude_prompt(tool['name'], tool['description'], tool['parameters'])
