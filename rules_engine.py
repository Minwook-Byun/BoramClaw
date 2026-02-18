#!/usr/bin/env python3
"""
rules_engine.py
Rules Engine - 규칙 기반 자동 액션 시스템

YAML 규칙 파일을 읽어서 조건을 평가하고 액션을 실행합니다.
"""
import sys
import yaml
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
import logging

# Context Engine import
from context_engine import ContextEngine

# macOS 알림 import
sys.path.insert(0, str(Path(__file__).parent))
from utils.macos_notify import notify as macos_notify

logger = logging.getLogger(__name__)


class RulesEngine:
    """규칙 기반 자동 액션 엔진"""

    def __init__(self, rules_file: str = "config/rules.yaml"):
        """
        Args:
            rules_file: 규칙 정의 YAML 파일 경로
        """
        self.rules_file = Path(rules_file)
        self.rules: list[dict[str, Any]] = []
        self.config: dict[str, Any] = {}
        self.context_engine = ContextEngine(lookback_minutes=30)
        self.last_context: Optional[dict[str, Any]] = None
        self.triggered_rules: dict[str, datetime] = {}  # 규칙 ID -> 마지막 트리거 시간

    def load_rules(self) -> bool:
        """
        YAML 파일에서 규칙 로드

        Returns:
            성공 여부
        """
        if not self.rules_file.exists():
            logger.warning(f"규칙 파일이 없습니다: {self.rules_file}")
            return False

        try:
            with open(self.rules_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            self.config = {
                "enabled": data.get("enabled", True),
                "check_interval": data.get("check_interval", 300),
            }

            self.rules = data.get("rules", [])
            logger.info(f"규칙 {len(self.rules)}개 로드 완료")
            return True

        except Exception as e:
            logger.error(f"규칙 로드 실패: {e}")
            return False

    def evaluate_rules(
        self,
        repo_path: str = ".",
        tool_executor: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        """
        모든 규칙 평가 및 액션 실행

        Args:
            repo_path: Git 저장소 경로
            tool_executor: 툴 실행기 (tool_call 액션용)

        Returns:
            실행된 액션 목록
        """
        if not self.config.get("enabled", True):
            return []

        # Context 조회
        context = self.context_engine.get_current_context(repo_path=repo_path)
        session = self.context_engine.detect_work_session(repo_path=repo_path)

        # 평가용 데이터 구성
        eval_data = {
            "context": context,
            "session": session,
            "git": context.get("activities", {}).get("git", {}),
            "shell": context.get("activities", {}).get("shell", {}),
            "browser": context.get("activities", {}).get("browser", {}),
            "time": {
                "hour": datetime.now().hour,
                "minute": datetime.now().minute,
                "day_of_week": datetime.now().strftime("%a").lower(),
            },
        }

        executed_actions = []

        for rule in self.rules:
            if not rule.get("enabled", True):
                continue

            rule_name = rule.get("name", "unnamed")

            # 조건 평가
            if self._evaluate_trigger(rule.get("trigger", {}), eval_data):
                # 이미 최근에 트리거된 규칙은 스킵 (중복 방지)
                if self._should_skip_duplicate(rule_name):
                    continue

                # 액션 실행
                actions = rule.get("actions", [])
                for action in actions:
                    result = self._execute_action(action, rule_name, tool_executor)
                    if result:
                        executed_actions.append({
                            "rule": rule_name,
                            "action": action.get("type"),
                            "result": result,
                            "timestamp": datetime.now().isoformat(),
                        })

                # 트리거 시간 기록
                self.triggered_rules[rule_name] = datetime.now()

        self.last_context = context
        return executed_actions

    def _evaluate_trigger(
        self,
        trigger: dict[str, Any],
        eval_data: dict[str, Any],
    ) -> bool:
        """
        트리거 조건 평가

        Args:
            trigger: 트리거 정의
            eval_data: 평가용 데이터

        Returns:
            조건 만족 여부
        """
        trigger_type = trigger.get("type")

        if trigger_type == "context_based":
            return self._evaluate_conditions(trigger.get("conditions", []), eval_data)

        elif trigger_type == "time_based":
            schedule = trigger.get("schedule", {})
            return self._evaluate_time_schedule(schedule, eval_data)

        elif trigger_type == "inactivity":
            return self._evaluate_inactivity(trigger.get("conditions", []), eval_data)

        elif trigger_type == "shell_pattern":
            return self._evaluate_shell_pattern(trigger.get("conditions", []), eval_data)

        elif trigger_type == "context_change":
            return self._evaluate_context_change(trigger.get("conditions", []), eval_data)

        return False

    def _evaluate_conditions(
        self,
        conditions: list[dict[str, Any]],
        eval_data: dict[str, Any],
    ) -> bool:
        """
        조건 리스트 평가 (AND 논리)

        Args:
            conditions: 조건 리스트
            eval_data: 평가용 데이터

        Returns:
            모든 조건 만족 여부
        """
        for condition in conditions:
            field = condition.get("field", "")
            operator = condition.get("operator", "equals")
            expected_value = condition.get("value")

            # 필드 값 추출
            actual_value = self._get_field_value(field, eval_data)

            # 조건 평가
            if not self._compare_values(actual_value, operator, expected_value):
                return False

        return True

    def _get_field_value(self, field: str, eval_data: dict[str, Any]) -> Any:
        """
        점 표기법 필드에서 값 추출

        Args:
            field: "context.summary.is_active" 같은 필드 경로
            eval_data: 평가용 데이터

        Returns:
            필드 값
        """
        parts = field.split(".")
        value = eval_data

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None

        return value

    def _compare_values(self, actual: Any, operator: str, expected: Any) -> bool:
        """
        값 비교

        Args:
            actual: 실제 값
            operator: 연산자
            expected: 기대 값

        Returns:
            비교 결과
        """
        if operator == "equals":
            return actual == expected
        elif operator == "not_equals":
            return actual != expected
        elif operator == "greater_than":
            return (actual or 0) > expected
        elif operator == "less_than":
            return (actual or 0) < expected
        elif operator == "greater_than_or_equal":
            return (actual or 0) >= expected
        elif operator == "less_than_or_equal":
            return (actual or 0) <= expected
        elif operator == "contains":
            return expected in (actual or "")
        elif operator == "not_contains":
            return expected not in (actual or "")
        return False

    def _evaluate_time_schedule(
        self,
        schedule: dict[str, Any],
        eval_data: dict[str, Any],
    ) -> bool:
        """
        시간 기반 스케줄 평가

        Args:
            schedule: {"time": "21:00", "days": ["mon", "tue"]}
            eval_data: 평가용 데이터

        Returns:
            현재 시간이 스케줄과 일치하는지
        """
        target_time = schedule.get("time", "")
        target_days = schedule.get("days", [])

        if not target_time:
            return False

        # 시간 파싱
        try:
            target_hour, target_minute = map(int, target_time.split(":"))
        except ValueError:
            return False

        current_hour = eval_data["time"]["hour"]
        current_minute = eval_data["time"]["minute"]
        current_day = eval_data["time"]["day_of_week"]

        # 시간 일치 (±1분 오차 허용)
        time_match = (
            current_hour == target_hour
            and abs(current_minute - target_minute) <= 1
        )

        # 요일 일치
        day_match = not target_days or current_day in target_days

        # 세션 조건 (선택)
        condition = schedule.get("condition")
        if condition == "session_active":
            session_active = eval_data.get("session", {}).get("is_session_active", False)
            return time_match and day_match and session_active

        return time_match and day_match

    def _evaluate_inactivity(
        self,
        conditions: list[dict[str, Any]],
        eval_data: dict[str, Any],
    ) -> bool:
        """
        비활동 트리거 평가

        Args:
            conditions: 조건 리스트
            eval_data: 평가용 데이터

        Returns:
            비활동 조건 만족 여부
        """
        # 간단히 context 활동 여부로 판단
        is_active = eval_data.get("context", {}).get("summary", {}).get("is_active", False)

        if is_active:
            return False

        return self._evaluate_conditions(conditions, eval_data)

    def _evaluate_shell_pattern(
        self,
        conditions: list[dict[str, Any]],
        eval_data: dict[str, Any]
    ) -> bool:
        """
        Shell 패턴 트리거 평가

        Args:
            conditions: 조건 리스트
            eval_data: 평가용 데이터

        Returns:
            Shell 패턴 조건 만족 여부
        """
        shell_data = eval_data.get("shell", {})
        top_commands = shell_data.get("top_commands", [])

        if not top_commands:
            return False

        # 가장 많이 사용한 명령어
        top_cmd = top_commands[0] if top_commands else {}

        # 조건에 사용할 데이터 추가
        eval_data["shell"]["top_command_count"] = top_cmd.get("count", 0)
        eval_data["shell"]["top_command_length"] = len(top_cmd.get("command", ""))

        return self._evaluate_conditions(conditions, eval_data)

    def _evaluate_context_change(
        self,
        conditions: list[dict[str, Any]],
        eval_data: dict[str, Any],
    ) -> bool:
        """
        컨텍스트 변경 트리거 평가

        Args:
            conditions: 조건 리스트
            eval_data: 평가용 데이터

        Returns:
            컨텍스트 변경 조건 만족 여부
        """
        # 이전 컨텍스트가 없으면 변경 감지 불가
        if not self.last_context:
            return False

        # 간단한 구현: Git 저장소 변경 감지
        current_repo = eval_data.get("git", {}).get("repo_path")
        last_repo = self.last_context.get("activities", {}).get("git", {}).get("repo_path")

        eval_data["git"]["repo_changed"] = current_repo != last_repo

        return self._evaluate_conditions(conditions, eval_data)

    def _execute_action(
        self,
        action: dict[str, Any],
        rule_name: str,
        tool_executor: Optional[Any] = None,
    ) -> Optional[str]:
        """
        액션 실행

        Args:
            action: 액션 정의
            rule_name: 규칙 이름
            tool_executor: 툴 실행기

        Returns:
            실행 결과 메시지
        """
        action_type = action.get("type")
        params = action.get("params", {})

        try:
            if action_type == "notification":
                return self._execute_notification(params)

            elif action_type == "tool_call":
                if tool_executor:
                    return self._execute_tool_call(params, tool_executor)
                else:
                    return "tool_executor not provided"

            elif action_type == "log":
                return self._execute_log(params, rule_name)

            elif action_type == "shell":
                return self._execute_shell(params)

            elif action_type == "webhook":
                return self._execute_webhook(params)

        except Exception as e:
            logger.error(f"액션 실행 실패 ({rule_name}): {e}")
            return f"error: {str(e)}"

        return None

    def _execute_notification(self, params: dict[str, Any]) -> str:
        """macOS 알림 실행"""
        title = params.get("title", "BoramClaw")
        message = params.get("message", "")
        sound = params.get("sound", "default")

        try:
            macos_notify(title, message, sound=sound)
            return f"notification sent: {title}"
        except Exception as e:
            return f"notification failed: {str(e)}"

    def _execute_tool_call(self, params: dict[str, Any], tool_executor: Any) -> str:
        """BoramClaw 툴 실행"""
        tool_name = params.get("tool_name", "")
        tool_input = params.get("tool_input", {})

        if not tool_name:
            return "tool_name not specified"

        try:
            result, is_error = tool_executor.run_tool(tool_name, tool_input)
            return f"tool executed: {tool_name}" if not is_error else f"tool failed: {result}"
        except Exception as e:
            return f"tool error: {str(e)}"

    def _execute_log(self, params: dict[str, Any], rule_name: str) -> str:
        """로그 기록"""
        message = params.get("message", "")
        level = params.get("level", "info")

        log_message = f"[{rule_name}] {message}"

        if level == "info":
            logger.info(log_message)
        elif level == "warning":
            logger.warning(log_message)
        elif level == "error":
            logger.error(log_message)

        return f"logged: {level}"

    def _execute_shell(self, params: dict[str, Any]) -> str:
        """Shell 명령 실행 (보안상 제한적)"""
        # 보안 위험으로 비활성화
        return "shell action disabled for security"

    def _execute_webhook(self, params: dict[str, Any]) -> str:
        """Webhook 호출 (미구현)"""
        return "webhook action not implemented"

    def _should_skip_duplicate(self, rule_name: str, cooldown_minutes: int = 60) -> bool:
        """
        중복 트리거 방지 (쿨다운)

        Args:
            rule_name: 규칙 이름
            cooldown_minutes: 쿨다운 시간 (분)

        Returns:
            스킵 여부
        """
        if rule_name not in self.triggered_rules:
            return False

        last_triggered = self.triggered_rules[rule_name]
        elapsed = (datetime.now() - last_triggered).total_seconds() / 60

        return elapsed < cooldown_minutes


if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)

    engine = RulesEngine("config/rules.yaml.example")
    if engine.load_rules():
        print(f"규칙 {len(engine.rules)}개 로드 완료")

        actions = engine.evaluate_rules()
        print(f"실행된 액션: {len(actions)}개")
        for action in actions:
            print(f"- {action}")
