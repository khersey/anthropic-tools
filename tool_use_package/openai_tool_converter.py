from typing import Any


def construct_openai_tool_use_system_prompt(tools: list[dict[str, Any]]) -> str:
    return (
        "In this environment you have access to a set of tools you can use to answer the user's question.\n"
        "\n"
        "You may call them like this:\n"
        "<function_calls>\n"
        "<invoke>\n"
        "<tool_name>$TOOL_NAME</tool_name>\n"
        "<parameters>\n"
        "<$PARAMETER_NAME>$PARAMETER_VALUE</$PARAMETER_NAME>\n"
        "...\n"
        "</parameters>\n"
        "</invoke>\n"
        "</function_calls>\n"
        "\n"
        "Here are the tools available:\n"
        "<tools>\n"
        + '\n'.join([convert_openai_tool(tool) for tool in tools]) +
        "\n</tools>"
    )

def convert_openai_tool(tool: dict[str, Any]) -> str:
    parameters = [] # list[dict]: name, type, description
    for property, info in tool['parameters']['properties'].items():
        parameters.append({
            'name': property,
            'type': info['type'],
            'description': info['description']
        })
    construct_format_tool_for_claude_prompt(tool['name'], tool['description'], parameters)

# anthropic utils:
def construct_format_parameters_prompt(parameters: dict[str, str]) -> str:
    return "\n".join(f"<parameter>\n<name>{parameter['name']}</name>\n<type>{parameter['type']}</type>\n<description>{parameter['description']}</description>\n</parameter>" for parameter in parameters)

def construct_format_tool_for_claude_prompt(name: str, description: str, parameters: dict[str, str]):
    return (
        "<tool_description>\n"
        f"<tool_name>{name}</tool_name>\n"
        "<description>\n"
        f"{description}\n"
        "</description>\n"
        "<parameters>\n"
        f"{construct_format_parameters_prompt(parameters)}\n"
        "</parameters>\n"
        "</tool_description>"
    )

