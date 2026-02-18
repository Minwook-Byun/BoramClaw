#!/usr/bin/env python3
"""
텔레그램 Chat ID 가져오기 도구

사용법:
1. BotFather에서 받은 토큰을 입력
2. 봇에게 /start 메시지를 보냄
3. 이 스크립트 실행
4. Chat ID를 받음
"""
import sys
import requests

def get_chat_id(bot_token):
    """텔레그램 봇의 Chat ID 가져오기"""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            print(f"❌ 오류: {data}")
            return None

        updates = data.get("result", [])
        if not updates:
            print("⚠️  메시지가 없습니다!")
            print("1. 텔레그램에서 봇을 찾으세요")
            print("2. /start 메시지를 보내세요")
            print("3. 다시 이 스크립트를 실행하세요")
            return None

        # 가장 최근 메시지에서 Chat ID 추출
        latest = updates[-1]
        chat = latest.get("message", {}).get("chat", {})
        chat_id = chat.get("id")
        username = chat.get("username", "Unknown")
        first_name = chat.get("first_name", "Unknown")

        print(f"\n✅ Chat ID를 찾았습니다!")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"👤 이름: {first_name}")
        print(f"🔑 Chat ID: {chat_id}")
        print(f"📱 Username: @{username}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

        return chat_id

    except requests.RequestException as e:
        print(f"❌ 네트워크 오류: {e}")
        return None
    except Exception as e:
        print(f"❌ 오류: {e}")
        return None


def main():
    print("\n🤖 텔레그램 Chat ID 가져오기\n")

    if len(sys.argv) < 2:
        print("사용법: python3 get_telegram_chat_id.py <BOT_TOKEN>")
        print("\n또는:")
        bot_token = input("봇 토큰을 입력하세요: ").strip()
    else:
        bot_token = sys.argv[1]

    if not bot_token:
        print("❌ 봇 토큰이 필요합니다!")
        sys.exit(1)

    chat_id = get_chat_id(bot_token)

    if chat_id:
        print("📝 .env 파일에 다음을 추가하세요:")
        print(f"\nTELEGRAM_BOT_TOKEN={bot_token}")
        print(f"TELEGRAM_ALLOWED_CHAT_ID={chat_id}")
        print(f"TELEGRAM_ENABLED=1\n")


if __name__ == "__main__":
    main()
