"""macOS 알림 센터 유틸리티.

사용법:
    from utils.macos_notify import notify
    notify("BoramClaw", "커밋 안 한 지 3시간입니다.")
"""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str, sound: str = "default",
           subtitle: str = "") -> bool:
    """macOS 알림 센터에 알림을 표시합니다.

    Args:
        title: 알림 제목
        message: 알림 본문
        sound: 알림 사운드 (기본 "default", 무음은 빈 문자열)
        subtitle: 알림 부제목 (선택)

    Returns:
        True if notification was sent successfully.
    """
    if sys.platform != "darwin":
        return False

    # AppleScript 문자열 이스케이프
    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script_parts = [f'display notification "{_esc(message)}"']
    script_parts.append(f'with title "{_esc(title)}"')
    if subtitle:
        script_parts.append(f'subtitle "{_esc(subtitle)}"')
    if sound:
        script_parts.append(f'sound name "{_esc(sound)}"')

    script = " ".join(script_parts)

    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5, check=False,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "BoramClaw"
    msg = sys.argv[2] if len(sys.argv) > 2 else "테스트 알림입니다."
    ok = notify(title, msg)
    print(f"알림 전송: {'성공' if ok else '실패'}")
