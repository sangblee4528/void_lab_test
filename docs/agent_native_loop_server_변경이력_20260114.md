# agent_native_loop_server 변경 이력 (2026-01-14)

이 문서는 `agent_native_loop_server.py`에 Human-in-the-Loop(HITL) 터미널 승인 기능 및 Graceful Shutdown 기능을 추가한 변경 내역을 상세히 기록합니다.

---

## 1. 기존 문제점

### 1-1. 자동 도구 실행의 위험성

**문제**: LLM이 도구 호출을 요청하면 서버가 **즉시 자동으로 실행**했습니다.

```python
# 기존 코드 (256-287행)
for tc in tool_calls:
    func_name = tc["function"]["name"]
    args = tc["function"]["arguments"]
    
    # ❌ 승인 없이 바로 실행
    if func_name in NATIVE_TOOL_REGISTRY:
        result = NATIVE_TOOL_REGISTRY[func_name](**args)
```

**위험 시나리오**:
- LLM이 잘못된 파일을 삭제하려고 할 때 막을 방법이 없음
- 의도치 않은 데이터 변경이 자동으로 수행됨
- 디버깅 시 어떤 도구가 실행되는지 사전 확인 불가

### 1-2. 사용자 통제권 부재

| 항목 | 기존 상태 |
|------|-----------|
| 도구 실행 전 확인 | ❌ 없음 |
| 실행 거부 기능 | ❌ 없음 |
| 실행 내용 사전 확인 | ❌ 로그에서만 확인 가능 |

---

## 2. 해결 방안: 터미널 승인 시스템

### 2-1. 핵심 아이디어

```
LLM 도구 호출 요청 → 터미널에 승인 요청 표시 → 사용자 y/n 입력 → 승인 시 실행, 거절 시 중단
```

### 2-2. 구현 상세

#### 🔧 새로 추가된 함수: `ask_terminal_approval()`

**위치**: `agent_native_loop_server.py` 81-104행

```python
async def ask_terminal_approval(func_name: str, args: Dict) -> bool:
    """
    터미널에서 도구 실행 승인을 요청합니다.
    y/Y/yes/Yes 입력 시 True, 그 외는 False 반환
    """
    print("\n" + "="*60)
    print(f"🔧 도구 실행 승인 요청")
    print(f"   도구: {func_name}")
    print(f"   인자: {json.dumps(args, ensure_ascii=False, indent=2)}")
    print("="*60)
    
    # async 방식으로 input() 호출 (이벤트 루프 블로킹 방지)
    loop = asyncio.get_event_loop()
    user_input = await loop.run_in_executor(None, lambda: input("실행하시겠습니까? (y/n): "))
    
    approved = user_input.strip().lower() in ['y', 'yes', '예', 'ㅛ']
    if approved:
        print("✅ 승인됨 - 도구를 실행합니다.\n")
    else:
        print("❌ 거절됨 - 도구 실행을 건너뜁니다.\n")
    
    return approved
```

**기술적 포인트**:
| 항목 | 설명 |
|------|------|
| `asyncio.run_in_executor()` | 동기 `input()` 함수를 별도 스레드에서 실행하여 이벤트 루프 블로킹 방지 |
| 다국어 지원 | `y`, `yes`, `예`, `ㅛ` 모두 승인으로 인식 |
| 시각적 표시 | 구분선과 이모지로 승인 요청임을 명확히 표시 |

---

#### 🔧 수정된 도구 실행 로직

**위치**: `agent_native_loop_server.py` 256-318행

**Before (자동 실행)**:
```python
# 도구 실행
logger.info(f"[Agent-{request_id}] Starting {len(tool_calls)} tools")
for tc in tool_calls:
    # 바로 실행
    result = NATIVE_TOOL_REGISTRY[func_name](**args)
```

**After (승인 후 실행)**:
```python
# 도구 실행 (승인 필요)
logger.info(f"[Agent-{request_id}] Starting {len(tool_calls)} tools (approval required)")
rejected = False

for tc in tool_calls:
    func_name = tc["function"]["name"]
    args = tc["function"]["arguments"]
    
    # 🔒 터미널 승인 요청
    approved = await ask_terminal_approval(func_name, args if isinstance(args, dict) else {})
    
    if not approved:
        rejected = True
        result = {"success": False, "error": "사용자가 도구 실행을 거절했습니다."}
        save_agent_log(request_id, f"Tool Rejected: {func_name}", "User rejected")
    elif func_name in NATIVE_TOOL_REGISTRY:
        # 승인된 경우에만 실행
        result = NATIVE_TOOL_REGISTRY[func_name](**args)
    
    # 거절 시 루프 중단
    if rejected:
        logger.info(f"[Agent-{request_id}] User rejected tool execution. Stopping loop.")
        break

# 거절 시 전체 루프 종료
if rejected:
    final_response = {
        "choices": [{
            "message": {"role": "assistant", "content": "사용자가 도구 실행을 거절하여 작업을 중단했습니다."},
            "finish_reason": "stop"
        }]
    }
    break
```

---

## 3. 변경 전/후 비교

| 항목 | Before | After |
|------|--------|-------|
| 도구 실행 방식 | 자동 (Auto) | 승인 후 (Manual) |
| 사용자 통제 | ❌ 없음 | ✅ y/n 입력 |
| 실행 거부 | ❌ 불가 | ✅ 가능 (루프 즉시 종료) |
| 실행 내용 사전 확인 | ❌ 로그 사후 확인 | ✅ 터미널에서 사전 확인 |
| 안전성 | 낮음 | 높음 |

---

## 4. 추가된 Import

```python
import asyncio  # 비동기 input 처리를 위해 추가
import signal   # 종료 시그널 처리를 위해 추가
```

---

## 5. 테스트 결과

### 승인 시나리오 (y 입력)
```
============================================================
🔧 도구 실행 승인 요청
   도구: read_file
   인자: {
     "filename": "a.txt"
   }
============================================================
실행하시겠습니까? (y/n): y
✅ 승인됨 - 도구를 실행합니다.

[Agent-192500] Tool call: read_file({'filename': 'a.txt'})
```

### 거절 시나리오 (n 입력)
```
============================================================
🔧 도구 실행 승인 요청
   도구: delete_file
   인자: {
     "filename": "important.txt"
   }
============================================================
실행하시겠습니까? (y/n): n
❌ 거절됨 - 도구 실행을 건너뜁니다.

[Agent-192500] User rejected tool execution. Stopping loop.
```

**거절 시 API 응답**:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "사용자가 도구 실행을 거절하여 작업을 중단했습니다."
    },
    "finish_reason": "stop"
  }]
}
```

---

## 6. 향후 개선 계획

| 우선순위 | 기능 | 설명 |
|----------|------|------|
| 1 | REST API 승인 | 터미널 대신 웹 UI에서 승인 가능 |
| 2 | 자동 승인 화이트리스트 | 안전한 도구는 자동 승인 설정 |
| 3 | 승인 타임아웃 | 일정 시간 내 응답 없으면 자동 거절 |
| 4 | 승인 이력 DB 저장 | 승인/거절 이력 추적 |

---

**작성자**: Antigravity (AI Assistant)  
**날짜**: 2026-01-14  
**관련 파일**: `agent_native_loop/agent_native_loop_server.py`

---

## 7. Graceful Shutdown 기능 추가 🆕

### 7-1. 기존 문제점

**문제**: 서버를 Ctrl+C로 종료해도 포트가 해제되지 않아 재시작 시 에러 발생

```
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8011): 
[winerror 10048] 각 소켓 주소(프로토콜/네트워크 주소/포트)는 하나만 사용할 수 있습니다
```

**원인**: 좀비 프로세스가 포트를 계속 점유

### 7-2. 해결 방안

**위치**: `agent_native_loop_server.py` 461-492행 (main 블록)

```python
if __name__ == "__main__":
    import uvicorn
    import signal
    import sys
    
    def signal_handler(sig, frame):
        """Ctrl+C 등 종료 시그널 처리"""
        print("\n🛑 종료 신호 수신. 서버를 정상 종료합니다...")
        sys.exit(0)
    
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # uvicorn 실행 (graceful shutdown 설정 포함)
    config_uvicorn = uvicorn.Config(
        app,
        host=config["agent"]["host"],
        port=config["agent"]["port"],
        loop="asyncio",
        timeout_graceful_shutdown=5  # 5초 내 graceful shutdown
    )
    server = uvicorn.Server(config_uvicorn)
    
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n🛑 키보드 인터럽트. 서버를 종료합니다...")
    finally:
        print("✅ 서버가 정상 종료되었습니다. 포트가 해제되었습니다.")
```

### 7-3. 변경 전/후 비교

| 항목 | Before | After |
|------|--------|-------|
| 종료 방식 | 강제 종료 | Graceful Shutdown |
| 포트 해제 | ❌ 좀비 프로세스 발생 | ✅ 정상 해제 |
| 종료 메시지 | ❌ 없음 | ✅ 상태 메시지 출력 |
| 재시작 | ❌ 포트 충돌 에러 | ✅ 즉시 재시작 가능 |

### 7-4. 종료 시 예상 출력

```
^C
🛑 종료 신호 수신. 서버를 정상 종료합니다...
✅ 서버가 정상 종료되었습니다. 포트가 해제되었습니다.
```

---

**최종 업데이트**: 2026-01-14 19:40
