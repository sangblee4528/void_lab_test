# Void Lab Test 진행 과정 보고서 (2026-01-06)

## 1. 개요
본 문서는 Void IDE와 Local Ollama 모델 간의 도구 호출 연동 문제를 해결하기 위해 도입된 **"Agent Proxy (Autonomous Agent)"** 아키텍처의 고도화 과정과 주요 기술적 해결 내역을 기록합니다.

---

## 2. 주요 아키텍처 전환: Passive Proxy → Autonomous Agent
- **이전 방식 (`proxy_server.py`)**: 클라이언트(Void UI)가 도구 실행 버튼을 만들기를 기다리는 수동적 방식. UI 파싱 오류에 취약함.
- **현재 방식 (`agent_proxy_server.py`)**: n8n의 상태 머신(State Machine) 루프를 차용하여, 서버가 직접 도구를 실행하고 결과를 LLM에게 재주입하는 자율적 방식. UI 의존성을 완전히 제거함.

---

## 3. 주요 문제 해결 및 기술적 조치

### 3.1. Void 초기화 404 에러 (Models Endpoint)
- **문제**: Void IDE 접속 시 `/v1/models`를 찾지 못해 초기화 오류 발생.
- **해결**: OpenAI 규격에 맞는 모델 목록 반환 엔드포인트 추가.
```python
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": config["ollama"]["model"], "object": "model", ...}]
    }
```

### 3.2. "Response from model was empty" 오류 해결
- **문제**: Void는 스트리밍(SSE)을 기대하는데, 서버가 단일 JSON만 반환하여 발생한 호환성 문제.
- **해결**: 최종 답변을 SSE 스트림 형식으로 포장하여 전달하는 **Pseudo-Streaming** 구현.
```python
if request.stream:
    return StreamingResponse(generate_pseudo_stream(final_resp), media_type="text/event-stream")
```

### 3.3. 마크다운 내 JSON 추출 (Fallback Logic 강화)
- **문제**: Ollama 모델이 `tool_calls` 필드 대신 본문(`content`)에 ` ```json ` 블록을 사용하여 도구를 호출할 때 인식하지 못함.
- **해결**: 정규표현식을 사용하여 텍스트나 코드 블록에 섞여 있는 JSON만 정확히 추출하는 로직 도입.
```python
if "```json" in json_str:
    json_str = re.search(r"```json\s*(.*?)\s*```", json_str, re.DOTALL).group(1)
```

### 3.4. 통합 및 구조화된 로그 시스템 구축
- **문제**: LLM과 MCP 사이의 통신 데이터 분석이 어려움.
- **해결**: 
    - `agent_proxy.log` 파일 기록 기능 추가.
    - `[LLM REQ]`, `[TOOL CALL]`, `[MCP RESP]` 등 명확한 태그와 구분자를 활용한 로깅 시스템 구축.

### 3.5. LLM Provider 범용화 (vLLM 및 OpenAI 지원)
- **문제**: 서버 로직과 설정이 Ollama에 종속되어 있어 vLLM 등 다른 LLM 엔진으로의 전환이 번거로움.
- **해결**: 
    - `ollama` 설정을 `llm` 섹션으로 통합하고 `base_url`, `api_key` 필드를 추가하여 모든 OpenAI 호환 API를 지원하도록 개편.
    - 소스 코드 내의 벤더 종속적 명칭(Ollama)을 범용 명칭(LLM)으로 리팩토링.
```json
"llm": {
    "provider": "vllm",
    "base_url": "http://127.0.0.1:8000/v1",
    "model": "qwen2.5-coder:7b",
    "api_key": "optional-key"
}
```

---

## 4. 최종 시스템 흐름 (State Machine)
1.  **[Thinking]**: 사용자의 질문을 Ollama에게 전달.
2.  **[Fallback]**: Ollama의 응답이 `tool_calls`든 마크다운 JSON이든 상관없이 구조화된 요청으로 변환.
3.  **[Action]**: 서버 내부의 `McpSseClient`가 직접 도구를 실행.
4.  **[Observation]**: 실행 결과를 대화 문맥에 추가하여 다시 Ollama에게 질문.
5.  **[Final Response]**: 답변이 완성되면 Void에게 SSE 스트림으로 결과 보고.

---

## 5. 향후 과제
- 툴 사용 시 실시간으로 사용자에게 "어떤 도구를 실행 중입니다"라는 중간 메시지를 보낼 수 있는 피드백 기능 검토.
- `tool_choice` 파라미터를 통한 강제 호출 옵션 추가.
