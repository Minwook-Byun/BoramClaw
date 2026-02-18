#!/usr/bin/env python3
"""
ollama_gateway.py
Ollama 로컬 LLM 통합 - Claude API 대체

Ollama는 로컬에서 LLM을 실행할 수 있는 오픈소스 도구입니다.
이 모듈은 Claude API와 동일한 인터페이스를 제공하여 완전 무료 운영을 가능하게 합니다.
"""
import json
import logging
from typing import Any, Callable, Optional
import requests

logger = logging.getLogger(__name__)


class OllamaChat:
    """Ollama 로컬 LLM 클라이언트 (Claude API 호환 인터페이스)"""

    def __init__(
        self,
        model: str = "llama3.2:3b",
        api_url: str = "http://localhost:11434",
        system_prompt: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ):
        """
        Args:
            model: Ollama 모델 이름 (llama3.2:3b, mistral:7b, qwen2.5:7b 등)
            api_url: Ollama API 엔드포인트
            system_prompt: 시스템 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 생성 온도 (0.0-1.0)
        """
        self.model = model
        self.api_url = api_url.rstrip("/")
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.conversation_history: list[dict[str, Any]] = []

        # Ollama 서버 연결 확인
        if not self._check_connection():
            logger.warning(f"Ollama 서버에 연결할 수 없습니다: {self.api_url}")

    def _check_connection(self) -> bool:
        """Ollama 서버 연결 확인"""
        try:
            response = requests.get(f"{self.api_url}/api/version", timeout=2)
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Ollama 연결 실패: {e}")
            return False

    def ask(
        self,
        prompt: str,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_runner: Optional[Callable[[str, dict[str, Any]], tuple[str, bool]]] = None,
        on_tool_event: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> str:
        """
        Ollama에게 질문 (Claude API 호환 인터페이스)

        Args:
            prompt: 사용자 질문
            tools: 사용 가능한 툴 목록
            tool_runner: 툴 실행 함수
            on_tool_event: 툴 이벤트 콜백

        Returns:
            Ollama 응답 텍스트
        """
        # 대화 이력에 사용자 메시지 추가
        self.conversation_history.append({"role": "user", "content": prompt})

        try:
            # Ollama API 호출
            response = self._call_ollama(prompt, tools)

            # 툴 호출이 필요한 경우 처리
            if tools and tool_runner and self._has_tool_call(response):
                return self._handle_tool_calls(
                    response,
                    tools,
                    tool_runner,
                    on_tool_event,
                )

            # 일반 응답
            assistant_message = response.get("message", {}).get("content", "")
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            return assistant_message

        except Exception as e:
            error_msg = f"Ollama 호출 실패: {e}"
            logger.error(error_msg)
            return f"[Ollama Error] {error_msg}"

    def _call_ollama(
        self,
        prompt: str,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Ollama API 호출"""
        # 메시지 구성
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # 대화 이력 추가
        messages.extend(self.conversation_history)

        # 툴 정보를 시스템 프롬프트에 추가
        if tools:
            tool_descriptions = self._format_tools_for_prompt(tools)
            messages[0]["content"] += f"\n\n사용 가능한 툴:\n{tool_descriptions}"

        # API 요청
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        response = requests.post(
            f"{self.api_url}/api/chat",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        return response.json()

    def _format_tools_for_prompt(self, tools: list[dict[str, Any]]) -> str:
        """툴 정보를 프롬프트 형식으로 변환"""
        tool_texts = []
        for tool in tools:
            name = tool.get("name", "unknown")
            description = tool.get("description", "")
            schema = tool.get("input_schema", {})
            properties = schema.get("properties", {})

            tool_text = f"- {name}: {description}"
            if properties:
                params = ", ".join(properties.keys())
                tool_text += f" (파라미터: {params})"
            tool_texts.append(tool_text)

        return "\n".join(tool_texts)

    def _has_tool_call(self, response: dict[str, Any]) -> bool:
        """응답에 툴 호출이 포함되어 있는지 확인"""
        # Ollama는 기본적으로 tool calling을 직접 지원하지 않음
        # 응답 텍스트를 파싱하여 툴 호출을 감지해야 함
        content = response.get("message", {}).get("content", "")
        return "<tool_call>" in content or "```json" in content

    def _handle_tool_calls(
        self,
        response: dict[str, Any],
        tools: list[dict[str, Any]],
        tool_runner: Callable[[str, dict[str, Any]], tuple[str, bool]],
        on_tool_event: Optional[Callable[[dict[str, Any]], None]],
    ) -> str:
        """툴 호출 처리 (간단한 구현)"""
        # Ollama는 native tool calling을 지원하지 않으므로
        # 응답 텍스트를 파싱하여 툴 호출을 추출해야 함
        # 여기서는 간단히 응답만 반환
        content = response.get("message", {}).get("content", "")
        self.conversation_history.append({"role": "assistant", "content": content})
        return content

    def reset_conversation(self):
        """대화 이력 초기화"""
        self.conversation_history = []

    def get_conversation_length(self) -> int:
        """대화 이력 길이"""
        return len(self.conversation_history)


class HybridChat:
    """
    Claude API + Ollama 하이브리드 클라이언트

    Claude API를 우선 사용하고, 실패 시 Ollama로 폴백
    """

    def __init__(
        self,
        claude_api_key: Optional[str] = None,
        claude_model: str = "claude-sonnet-4-5-20250929",
        ollama_model: str = "llama3.2:3b",
        ollama_url: str = "http://localhost:11434",
        prefer_local: bool = False,
        system_prompt: str = "",
    ):
        """
        Args:
            claude_api_key: Claude API 키 (없으면 Ollama만 사용)
            claude_model: Claude 모델 이름
            ollama_model: Ollama 모델 이름
            ollama_url: Ollama API URL
            prefer_local: True면 Ollama 우선 사용
            system_prompt: 시스템 프롬프트
        """
        self.prefer_local = prefer_local
        self.claude_client: Optional[Any] = None
        self.ollama_client: Optional[OllamaChat] = None

        # Claude 클라이언트 초기화
        if claude_api_key:
            try:
                from gateway import ClaudeChat
                self.claude_client = ClaudeChat(
                    api_key=claude_api_key,
                    model=claude_model,
                    system_prompt=system_prompt,
                )
                logger.info("Claude API 클라이언트 초기화 완료")
            except Exception as e:
                logger.warning(f"Claude API 초기화 실패: {e}")

        # Ollama 클라이언트 초기화
        try:
            self.ollama_client = OllamaChat(
                model=ollama_model,
                api_url=ollama_url,
                system_prompt=system_prompt,
            )
            if self.ollama_client._check_connection():
                logger.info(f"Ollama 클라이언트 초기화 완료 (모델: {ollama_model})")
            else:
                logger.warning("Ollama 서버에 연결할 수 없습니다")
                self.ollama_client = None
        except Exception as e:
            logger.warning(f"Ollama 초기화 실패: {e}")
            self.ollama_client = None

        # 사용 가능한 클라이언트 확인
        if not self.claude_client and not self.ollama_client:
            raise RuntimeError("Claude API와 Ollama 모두 사용할 수 없습니다")

    def ask(
        self,
        prompt: str,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_runner: Optional[Callable[[str, dict[str, Any]], tuple[str, bool]]] = None,
        on_tool_event: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> str:
        """
        하이브리드 질문 (Claude → Ollama 폴백)

        Args:
            prompt: 사용자 질문
            tools: 사용 가능한 툴 목록
            tool_runner: 툴 실행 함수
            on_tool_event: 툴 이벤트 콜백

        Returns:
            LLM 응답 텍스트
        """
        # 로컬 우선 모드
        if self.prefer_local and self.ollama_client:
            try:
                logger.debug("Ollama (로컬) 사용")
                return self.ollama_client.ask(prompt, tools, tool_runner, on_tool_event)
            except Exception as e:
                logger.warning(f"Ollama 실패, Claude로 폴백: {e}")
                if self.claude_client:
                    return self.claude_client.ask(prompt, tools, tool_runner, on_tool_event)
                raise

        # Claude 우선 모드 (기본)
        if self.claude_client:
            try:
                logger.debug("Claude API 사용")
                return self.claude_client.ask(prompt, tools, tool_runner, on_tool_event)
            except Exception as e:
                logger.warning(f"Claude 실패, Ollama로 폴백: {e}")
                if self.ollama_client:
                    return self.ollama_client.ask(prompt, tools, tool_runner, on_tool_event)
                raise

        # Ollama만 사용 가능
        if self.ollama_client:
            logger.debug("Ollama (로컬) 사용 (Claude 없음)")
            return self.ollama_client.ask(prompt, tools, tool_runner, on_tool_event)

        raise RuntimeError("사용 가능한 LLM 클라이언트가 없습니다")

    def reset_conversation(self):
        """대화 이력 초기화"""
        if self.claude_client:
            self.claude_client.reset_conversation()
        if self.ollama_client:
            self.ollama_client.reset_conversation()


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)

    # Ollama 단독 테스트
    print("=== Ollama 단독 테스트 ===")
    try:
        ollama = OllamaChat(model="llama3.2:3b")
        response = ollama.ask("안녕하세요! 간단한 자기소개 해주세요.")
        print(f"Ollama 응답: {response}\n")
    except Exception as e:
        print(f"Ollama 테스트 실패: {e}\n")

    # 하이브리드 테스트
    print("=== 하이브리드 테스트 (Ollama 우선) ===")
    try:
        hybrid = HybridChat(
            claude_api_key=None,  # Claude 없이
            ollama_model="llama3.2:3b",
            prefer_local=True,
        )
        response = hybrid.ask("1 + 1은?")
        print(f"하이브리드 응답: {response}\n")
    except Exception as e:
        print(f"하이브리드 테스트 실패: {e}\n")
