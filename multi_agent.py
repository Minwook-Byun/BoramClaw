from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AgentProfile:
    name: str
    description: str
    system_instruction: str
    force_tool_use_default: bool = False


AGENT_PROFILES: dict[str, AgentProfile] = {
    "general": AgentProfile(
        name="general",
        description="일반 대화/질의 응답",
        system_instruction="일반 어시스턴트 역할로 응답하되, 필요 시 도구를 우선 사용하세요.",
        force_tool_use_default=False,
    ),
    "research": AgentProfile(
        name="research",
        description="논문/조사/요약",
        system_instruction=(
            "리서치 에이전트 역할입니다. 추측보다 근거 수집을 우선하고, "
            "가능하면 도구를 먼저 호출해 데이터 기반으로 답하세요."
        ),
        force_tool_use_default=True,
    ),
    "ops": AgentProfile(
        name="ops",
        description="일정/운영/모니터링",
        system_instruction=(
            "운영 에이전트 역할입니다. 작업을 실행 가능한 단계로 분해하고, "
            "도구 실행 결과를 중심으로 상태를 보고하세요."
        ),
        force_tool_use_default=True,
    ),
    "builder": AgentProfile(
        name="builder",
        description="코드/도구 생성",
        system_instruction=(
            "빌더 에이전트 역할입니다. 먼저 기존 도구를 탐색하고 재사용을 우선하며, "
            "필요할 때만 도구 생성/수정을 수행하세요."
        ),
        force_tool_use_default=True,
    ),
}


def decide_agent(prompt: str) -> dict[str, str]:
    text = (prompt or "").strip().lower()
    if not text:
        return {"agent": "general", "reason": "empty_prompt"}

    research_tokens = (
        "arxiv",
        "논문",
        "paper",
        "research",
        "요약",
        "deepseek",
        "딥시크",
    )
    ops_tokens = (
        "calendar",
        "캘린더",
        "일정",
        "스케줄",
        "watchdog",
        "health",
        "운영",
        "daemon",
    )
    builder_tokens = (
        "도구",
        "tool",
        "plugin",
        "플러그인",
        "코드",
        "구현",
        "수정",
        "생성",
        "리팩터",
    )

    if any(token in text for token in research_tokens):
        return {"agent": "research", "reason": "research_keywords"}
    if any(token in text for token in ops_tokens):
        return {"agent": "ops", "reason": "ops_keywords"}
    if any(token in text for token in builder_tokens):
        return {"agent": "builder", "reason": "builder_keywords"}
    return {"agent": "general", "reason": "default"}


def format_agent_selection(selection: dict[str, str]) -> str:
    agent_name = str(selection.get("agent", "general"))
    reason = str(selection.get("reason", ""))
    profile = AGENT_PROFILES.get(agent_name, AGENT_PROFILES["general"])
    return f"에이전트 선택: {profile.name} ({profile.description}) / reason={reason}"


class MultiAgentCoordinator:
    def __init__(self) -> None:
        self.profiles = AGENT_PROFILES

    def handle_turn(
        self,
        *,
        chat: Any,
        user_input: str,
        select_tool_specs: Callable[[str], tuple[list[dict[str, Any]], dict[str, Any]]],
        tool_runner: Callable[[str, dict[str, Any]], tuple[str, bool]],
        on_tool_event: Callable[[str, dict[str, Any], str, bool], None],
        force_tool_use: bool = False,
    ) -> dict[str, Any]:
        selection = decide_agent(user_input)
        profile = self.profiles.get(selection.get("agent", "general"), self.profiles["general"])
        specs, schema_report = select_tool_specs(user_input)

        original_system = str(getattr(chat, "system_prompt", ""))
        original_force = bool(getattr(chat, "force_tool_use", False))
        setattr(
            chat,
            "system_prompt",
            f"{original_system}\n\n[DelegatedAgent:{profile.name}] {profile.system_instruction}",
        )
        setattr(chat, "force_tool_use", original_force or force_tool_use or profile.force_tool_use_default)
        try:
            answer = chat.ask(
                user_input,
                tools=specs,
                tool_runner=tool_runner,
                on_tool_event=on_tool_event,
            )
        finally:
            setattr(chat, "system_prompt", original_system)
            setattr(chat, "force_tool_use", original_force)

        return {
            "answer": answer,
            "agent": profile.name,
            "agent_reason": selection.get("reason", ""),
            "schema_report": schema_report,
        }
