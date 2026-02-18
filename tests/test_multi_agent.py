from __future__ import annotations

import unittest

from multi_agent import MultiAgentCoordinator, decide_agent


class FakeChat:
    def __init__(self) -> None:
        self.system_prompt = "base prompt"
        self.force_tool_use = False
        self.calls: list[dict] = []

    def ask(self, user_input, tools=None, tool_runner=None, on_tool_event=None):  # noqa: ANN001,ANN201
        self.calls.append(
            {
                "user_input": user_input,
                "tools": tools or [],
                "system_prompt": self.system_prompt,
                "force_tool_use": self.force_tool_use,
            }
        )
        return "ok"


class TestMultiAgent(unittest.TestCase):
    def test_decide_agent(self) -> None:
        self.assertEqual(decide_agent("아카이브 논문 요약"), {"agent": "research", "reason": "research_keywords"})
        self.assertEqual(decide_agent("캘린더 일정 확인"), {"agent": "ops", "reason": "ops_keywords"})
        self.assertEqual(decide_agent("도구 코드를 수정해"), {"agent": "builder", "reason": "builder_keywords"})
        self.assertEqual(decide_agent("안녕"), {"agent": "general", "reason": "default"})

    def test_coordinator_delegates_with_role_instruction(self) -> None:
        chat = FakeChat()
        coordinator = MultiAgentCoordinator()

        def selector(prompt: str):
            self.assertIn("논문", prompt)
            return ([{"name": "arxiv_daily_digest"}], {"selected_tool_count": 1, "total_tool_count": 3})

        result = coordinator.handle_turn(
            chat=chat,
            user_input="논문 3개 요약해줘",
            select_tool_specs=selector,
            tool_runner=lambda name, data: ("{}", False),
            on_tool_event=lambda *_args, **_kwargs: None,
            force_tool_use=False,
        )

        self.assertEqual(result["answer"], "ok")
        self.assertEqual(result["agent"], "research")
        self.assertEqual(len(chat.calls), 1)
        self.assertIn("DelegatedAgent:research", chat.calls[0]["system_prompt"])
        self.assertTrue(chat.calls[0]["force_tool_use"])
        self.assertEqual(chat.system_prompt, "base prompt")
        self.assertFalse(chat.force_tool_use)


if __name__ == "__main__":
    unittest.main()
