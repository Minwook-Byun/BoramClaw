#!/usr/bin/env python3
"""
텔레그램 봇 테스트 스크립트

사용법:
  python3 test_telegram.py
"""
import sys
import os
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from tools.telegram_send_message import run as telegram_send

def main():
    print("\n🤖 텔레그램 봇 테스트\n")

    # .env 파일 확인
    env_file = project_root / ".env"
    if not env_file.exists():
        print("❌ .env 파일이 없습니다!")
        sys.exit(1)

    # 환경 변수 로드 (파일에서 읽고 os.environ에 설정)
    bot_token = None
    chat_id = None
    enabled = None

    for line in env_file.read_text().split("\n"):
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN=") and not line.startswith("#"):
            bot_token = line.split("=", 1)[1].strip()
            os.environ["TELEGRAM_BOT_TOKEN"] = bot_token
        elif line.startswith("TELEGRAM_ALLOWED_CHAT_ID=") and not line.startswith("#"):
            chat_id = line.split("=", 1)[1].strip()
            os.environ["TELEGRAM_ALLOWED_CHAT_ID"] = chat_id
        elif line.startswith("TELEGRAM_ENABLED=") and not line.startswith("#"):
            enabled = line.split("=", 1)[1].strip()
            os.environ["TELEGRAM_ENABLED"] = enabled

    # 설정 확인
    if not bot_token or bot_token == "your_bot_token_here":
        print("❌ TELEGRAM_BOT_TOKEN이 설정되지 않았습니다!")
        print("\n다음 단계:")
        print("1. BotFather에서 봇 토큰을 받으세요")
        print("2. .env 파일에서 TELEGRAM_BOT_TOKEN=... 라인의 주석(#)을 제거하고 토큰을 입력하세요")
        sys.exit(1)

    if not chat_id or chat_id == "your_chat_id_here":
        print("❌ TELEGRAM_ALLOWED_CHAT_ID가 설정되지 않았습니다!")
        print("\n다음 단계:")
        print("1. 봇에게 /start 메시지를 보내세요")
        print(f"2. python3 get_telegram_chat_id.py {bot_token[:20]}... 실행")
        print("3. .env 파일에서 TELEGRAM_ALLOWED_CHAT_ID=... 라인의 주석(#)을 제거하고 Chat ID를 입력하세요")
        sys.exit(1)

    if enabled != "1":
        print("⚠️  TELEGRAM_ENABLED=1로 설정되지 않았습니다")
        print(".env 파일에서 TELEGRAM_ENABLED=1 라인의 주석(#)을 제거하세요")
        sys.exit(1)

    # 설정 출력
    print("✅ 설정 확인:")
    print(f"   Bot Token: {bot_token[:20]}...")
    print(f"   Chat ID: {chat_id}")
    print(f"   Enabled: {enabled}\n")

    # 테스트 메시지 전송
    print("📤 테스트 메시지 전송 중...\n")

    result = telegram_send(
        {
            "text": "🎉 BoramClaw 텔레그램 연동 성공!\n\n이제 다음 명령어로 리포트를 받을 수 있습니다:\n- /tool workday_recap {\"mode\":\"daily\"}\n- /tool workday_recap {\"mode\":\"weekly\"}\n\n또는 간단하게:\n- boram today\n- boram week"
        },
        {}
    )

    # 디버깅용 출력
    print(f"Debug - Result: {result}\n")

    if result.get("ok"):
        print("✅ 메시지 전송 성공!")
        print("\n📱 텔레그램 앱을 확인해보세요!")
    else:
        print(f"❌ 메시지 전송 실패: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
