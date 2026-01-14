"""
test_loop_api.py - 테스트 클라이언트

Agent Loop API 서버를 테스트하는 클라이언트입니다.
도구 실행 승인이 필요할 때 사용자에게 y/n 프롬프트를 표시합니다.
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8012"


def print_separator(title=""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


def chat(message: str):
    """채팅 요청"""
    print_separator(f"채팅 요청: {message}")
    
    payload = {
        "model": "qwen2.5-coder:7b",
        "messages": [{"role": "user", "content": message}],
        "stream": False
    }
    
    try:
        response = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload)
        data = response.json()
        
        # 승인 필요 여부 확인
        if data.get("approval_required"):
            pending = data.get("pending_approval", {})
            request_id = pending.get("request_id")
            tool_calls = pending.get("tool_calls", [])
            
            print("\n🔧 도구 실행 승인 요청:")
            for tc in tool_calls:
                print(f"   - {tc['name']}: {json.dumps(tc['arguments'], ensure_ascii=False)}")
            
            # 사용자 입력 받기
            user_input = input("\n실행하시겠습니까? (y/n): ").strip().lower()
            
            if user_input in ['y', 'yes', '예', 'ㅛ']:
                print("\n✅ 승인 중...")
                return approve(request_id)
            else:
                print("\n❌ 거절 중...")
                return reject(request_id)
        else:
            # 승인 필요 없음 - 바로 응답
            print("\n📝 응답:")
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                print(content)
            return data
            
    except Exception as e:
        print(f"❌ 오류: {e}")
        return None


def approve(request_id: str):
    """승인 요청"""
    try:
        response = requests.post(f"{BASE_URL}/v1/approve/{request_id}")
        data = response.json()
        
        print("\n📝 최종 응답:")
        if "response" in data:
            choices = data["response"].get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                print(content)
        
        return data
    except Exception as e:
        print(f"❌ 승인 오류: {e}")
        return None


def reject(request_id: str):
    """거절 요청"""
    try:
        response = requests.post(f"{BASE_URL}/v1/reject/{request_id}")
        data = response.json()
        print(f"\n📝 거절됨: {data.get('message')}")
        return data
    except Exception as e:
        print(f"❌ 거절 오류: {e}")
        return None


def check_pending():
    """대기 중인 요청 확인"""
    print_separator("대기 중인 요청")
    try:
        response = requests.get(f"{BASE_URL}/v1/pending")
        data = response.json()
        
        pending = data.get("pending", [])
        if pending:
            for p in pending:
                print(f"  - {p['request_id']}: {', '.join(p['tools'])}")
        else:
            print("  대기 중인 요청이 없습니다.")
        
        return data
    except Exception as e:
        print(f"❌ 오류: {e}")
        return None


def check_server():
    """서버 상태 확인"""
    print_separator("서버 상태")
    try:
        response = requests.get(f"{BASE_URL}/")
        data = response.json()
        print(f"  상태: {data.get('status')}")
        print(f"  에이전트: {data.get('agent')}")
        return True
    except Exception as e:
        print(f"❌ 서버 연결 실패: {e}")
        return False


def main():
    print("\n" + "=" * 60)
    print("  Agent Loop API 테스트 클라이언트")
    print("=" * 60)
    
    # 서버 상태 확인
    if not check_server():
        print("\n서버가 실행 중이 아닙니다. 먼저 서버를 실행해주세요:")
        print("  python agent_loop_api_server.py")
        return
    
    # 대화형 모드
    print("\n명령어:")
    print("  /quit - 종료")
    print("  /pending - 대기 중인 요청 확인")
    print("  그 외 - 채팅 메시지")
    
    while True:
        try:
            user_input = input("\n💬 입력: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['/quit', '/exit', '/q']:
                print("\n👋 종료합니다.")
                break
            
            if user_input.lower() == '/pending':
                check_pending()
                continue
            
            # 채팅
            chat(user_input)
            
        except KeyboardInterrupt:
            print("\n\n👋 종료합니다.")
            break


if __name__ == "__main__":
    main()
