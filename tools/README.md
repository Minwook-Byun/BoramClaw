# tools directory

Place custom local tool files (`*.py`) here.

`main.py` does not import these files directly.
Each tool is executed as an external subprocess.

Required contract per file:

- `TOOL_SPEC` (dict):
  - `name`: unique tool name
  - `description`: short description
  - `version`: semantic version string
  - `input_schema`: JSON schema for tool input
- `run(input_data: dict, context: dict) -> Any`
- CLI entrypoint:
  - must include `if __name__ == "__main__": ...`
  - must support `--tool-spec-json` (prints JSON TOOL_SPEC)
  - must support `--tool-input-json` and `--tool-context-json` (prints JSON run result)

The assistant discovers tools from filesystem on each tool call.
- list tools: `/tools` or `/tool list_custom_tools {}`
- sync tools: `/sync-tools` or `/tool reload_custom_tools {}`
- filesystem status: `/tool tool_registry_status {}`
- create/update tool file: `/tool create_or_update_custom_tool_file {"file_name":"my_tool.py","content":"..." }`
- delete tool file: `/tool delete_custom_tool_file {"file_name":"my_tool.py","purge_related_schedules":true}`
- schedule daily run: `/tool schedule_daily_tool {"tool_name":"my_tool","time":"09:00","tool_input":{}}`
- list schedules: `/schedules` or `/tool list_scheduled_jobs {}`

Gmail example:
- test once: `/tool gmail_reply_recommender {"query":"is:unread newer_than:1d","max_messages":10}`
- test once + send: `/tool gmail_reply_recommender {"query":"is:unread newer_than:1d","max_messages":5,"send_messages":true}`
- daily 09:00 schedule:
  `/tool schedule_daily_tool {"tool_name":"gmail_reply_recommender","time":"09:00","tool_input":{"query":"is:unread newer_than:1d","max_messages":20,"create_drafts":true}}`
- daily 09:00 schedule + send:
  `/tool schedule_daily_tool {"tool_name":"gmail_reply_recommender","time":"09:00","tool_input":{"query":"is:unread newer_than:1d","max_messages":20,"send_messages":true,"mark_as_read":true}}`

arXiv example:
- test once:
  `/tool arxiv_daily_digest {"keywords":["machine learning","llm"],"max_papers":5,"output":"text"}`
- save to file:
  `/tool arxiv_daily_digest {"keywords":["reinforcement learning"],"max_papers":10,"output":"file","output_file":"logs/daily_arxiv.md"}`

Context fields:
- `workdir`
- `default_timeout_seconds`
- `max_output_chars`

For always-on automation:
- set `AGENT_MODE=daemon` in `.env`
- run `python3 main.py` in a long-running process (tmux/nohup/launchd)

Defensive behavior:
- if `tools/*.py` changes, chat session is recreated with short summary memory.
- `STRICT_WORKDIR_ONLY=1` (default): blocks parent-directory access, absolute path shell args, and `run_python`.
