# agent_loop_api_routes.py 변경 사항 (2026-01-15)

## 개요
네이티브 도구 호출 시 발생하는 `400 Bad Request` 오류와 LLM이 도구 결과를 요약하지 못하고 도구 호출을 반복하는 문제를 해결하기 위해 코드를 수정했습니다.

## 주요 변경 내용

### 1. 도구 호출 인자 포맷 수정 (`detect_tool_calls`)
- **문제점**: Ollama(또는 호환되는 API)가 도구 호출의 `arguments` 필드를 JSON 문자열로 요구하지만, 기존 로직은 Python 딕셔너리 그대로 전달하여 `400 Bad Request` 오류 발생.
- **수정**: `arguments`가 딕셔너리인 경우 `json.dumps()`를 사용하여 JSON 문자열로 변환하도록 수정.

```python
# 수정 전
"arguments": potential.get("arguments") or potential.get("args") or {}

# 수정 후
args_payload = potential.get("arguments") or potential.get("args") or {}
if isinstance(args_payload, dict):
    args_payload = json.dumps(args_payload, ensure_ascii=False)
"arguments": args_payload
```

### 2. 어시스턴트 메시지 컨텐츠 초기화 (`chat_completions`)
- **문제점**: 텍스트로 감지된 도구 호출을 `tool_calls` 필드로 변환하여 주입할 때, 기존 텍스트 `content`가 남아있으면 LLM이 "이미 답변을 했다"고 착각하거나, 문맥이 꼬여서 도구 결과를 처리하지 않고 다시 도구를 호출하는 현상 발생.
- **수정**: 감지된 도구 호출을 `assistant_msg`에 주입할 때, `content` 필드를 `None`으로 강제 설정하여 LLM이 명확하게 도구 호출 상태임을 인지하도록 변경.

```python
# 추가된 코드
if tool_calls and not assistant_msg.get("tool_calls"):
    assistant_msg["tool_calls"] = tool_calls
    assistant_msg["content"] = None  # <-- 이 부분 추가
```

## 결과
- `verify_api_flow_clean.py` 검증 스크립트 실행 시, 직원 목록이 정상적으로 조회되고 LLM이 이를 바탕으로 최종 답변을 생성함.
- `[SUCCESS] Verification Successful: Employee list found in response.`
