# Local Custom Tools

Each `.py` file in this directory can register one tool.

Required exports:

1. `TOOL_SPEC` (dict)
- `name`: unique tool name
- `description`: short description
- `input_schema`: JSON schema object for tool input

2. `run(input_data: dict, context: dict) -> Any`
- `input_data`: tool arguments from the model or `/tool` command
- `context`: runtime context
  - `workdir`
  - `default_timeout_seconds`
  - `max_output_chars`

After creating or editing tools, use `/reload-tools` in chat.
List loaded tools with `/tools`.
