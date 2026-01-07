# agent_proxy_server.py 변경 이력 - 2026년 1월 6일

## 변경 일시
2026-01-06 23:08

## 변경 파일
- `agent_proxy/agent_proxy_server.py`

## 변경 사유
Void IDE 채팅창에서 도구(Tool) 호출 후 최종 응답이 표시되지 않는 문제 해결

## 문제 상황
- 일반 질문("안녕하세요")은 정상 표시됨
- 도구 사용 질문("직원 명단을 주세요")은 서버 로그에서 응답 생성 확인되나 Void 채팅창에 표시 안 됨
- 로그: `✅ [Agent-211753] 최종 응답 도달` 및 `200 OK` 확인됨

## 원인 분석
`generate_pseudo_stream()` 함수가 OpenAI 스트리밍 규격을 완전히 따르지 않음:
- **기존**: role과 content를 하나의 청크에 함께 전송
- **문제**: Void IDE가 스트리밍 메시지를 제대로 파싱하지 못함

## 변경 내용

### 수정 전 코드 (304-323행)
```python
def generate_pseudo_stream(final_resp: Dict):
    """일반 응답을 SSE 스트림 형식으로 변환"""
    chunk = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": final_resp["choices"][0]["message"]["content"]
                },
                "finish_reason": "stop"
            }
        ]
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\\n\\n"
    yield "data: [DONE]\\n\\n"
```

### 수정 후 코드 (304-353행)
```python
def generate_pseudo_stream(final_resp: Dict):
    """일반 응답을 SSE 스트림 형식으로 변환"""
    # 첫 번째 청크: role만 전송
    chunk1 = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None
            }
        ]
    }
    yield f"data: {json.dumps(chunk1, ensure_ascii=False)}\\n\\n"
    
    # 두 번째 청크: content 전송
    chunk2 = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {"content": final_resp["choices"][0]["message"]["content"]},
                "finish_reason": None
            }
        ]
    }
    yield f"data: {json.dumps(chunk2, ensure_ascii=False)}\\n\\n"
    
    # 세 번째 청크: finish_reason
    chunk3 = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }
        ]
    }
    yield f"data: {json.dumps(chunk3, ensure_ascii=False)}\\n\\n"
    yield "data: [DONE]\\n\\n"
```

## 주요 개선 사항

1. **3단계 청크 분리**
   - Chunk 1: `role: assistant` 전송
   - Chunk 2: `content` 전송
   - Chunk 3: `finish_reason: stop` 전송

2. **OpenAI 스트리밍 규격 준수**
   - 각 청크의 `finish_reason`을 적절히 설정 (`None` → `None` → `"stop"`)
   - `delta` 객체에 필요한 필드만 포함

3. **Void IDE 호환성 향상**
   - 명시적인 role 전송으로 메시지 인식률 향상
   - 표준 스트리밍 포맷으로 렌더링 문제 해결

## 복구 방법 (롤백)
이 변경을 되돌리려면 "수정 전 코드"를 304-323행에 다시 붙여넣으세요.

## 테스트 방법
1. `agent_proxy_server.py` 재시작
2. Void IDE 채팅창에서 도구 사용 질문 입력 (예: "직원 명단을 주세요")
3. 응답이 채팅창에 정상 표시되는지 확인

## 참고 자료
- OpenAI Streaming API: https://platform.openai.com/docs/api-reference/streaming
- SSE (Server-Sent Events) 표준
