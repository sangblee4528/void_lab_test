# Agent Proxy 시스템 아키텍처 문서

## 1. 개요
본 문서는 Void IDE의 도구 실행 제약(UI 파싱 문제)을 극복하기 위해 설계된 **"Agent Proxy System"**의 아키텍처와 기술 명세를 다룹니다. 이 시스템은 n8n의 **"Looping & State Machine"** 방식을 차용하여, 클라이언트(UI)가 아닌 서버가 주도적으로 도구를 실행하고 결과를 관리하는 **자율 에이전트(Autonomous Agent)** 모델을 구현합니다.

## 2. 시스템 구성도
전체 시스템은 크게 두 가지 핵심 모듈로 구성됩니다.

| 모듈명 | 파일 위치 | 역할 | n8n 비유 |
| :--- | :--- | :--- | :--- |
| **Agent Server** | `agent_proxy/agent_proxy_server.py` | 자율 실행 루프 및 상태 관리 | **Workflow Engine** |
| **MCP Client** | `agent_proxy/mcp_client.py` | 도구 서버와의 통신 전담 | **HTTP Request Node** |

---

## 3. 모듈별 상세 명세

### 3.1. Agent Proxy Server (`agent_proxy_server.py`)
이 모듈은 AI 에이전트의 **"두뇌(Brain)"** 역할을 수행합니다. 사용자의 요청을 받으면, 최종 답변이 완성될 때까지 스스로 **"생각(LLM) -> 행동(Tool) -> 관찰(Response)"** 사이클을 반복합니다.

#### 주요 기능
1.  **Autonomous Loop (자율 반복 루프)**:
    -   `POST /v1/chat/completions` 요청을 받으면 즉시 응답하지 않고 내부 루프(`max_iterations = 5`)를 시작합니다.
    -   LLM이 도구 호출(`tool_calls`)을 요청하면, 이를 클라이언트에게 보내지 않고 **서버 내부에서 가로챕니다.**

2.  **State Management (상태 관리)**:
    -   대화의 맥락(`current_messages`)을 메모리에 유지하며, 도구 실행 결과(`role: tool`)를 대화 기록에 누적시킵니다.
    -   이를 통해 LLM은 이전 단계의 실행 결과를 바탕으로 다음 행동을 결정할 수 있습니다.

3.  **Protocol Translation (프로토콜 변환)**:
    -   Ollama의 응답 포맷과 OpenAI의 포맷 차이를 내부적으로 조율합니다.
    -   특히 `content`에 문자열로 섞여 나오는 JSON을 파싱하여 구조화된 `tool_calls` 객체로 자동 변환하는 **Fallback Logic**이 포함되어 있습니다.

#### 코드 구조 (핵심 로직)
```python
# 루프 진입
for i in range(max_iterations):
    # 1. LLM에게 질문
    response = await call_ollama(history)
    
    # 2. 도구 호출 확인
    if response.tool_calls:
        # 3. 직접 실행 (클라이언트에게 위임 X)
        result = await mcp_client.call_tool(name, args)
        
        # 4. 결과 주입
        history.append({
            "role": "tool",
            "content": result
        })
    else:
        # 5. 최종 답변 반환
        return response
```

---

### 3.2. MCP SSE Client (`mcp_client.py`)
이 모듈은 MCP(Model Context Protocol) 서버와 통신하기 위한 **"팔다리(Actuator)"** 역할을 수행합니다. 표준 SSE(Server-Sent Events) 방식을 사용하여 안정적인 양방향 통신을 보장합니다.

#### 주요 기능
1.  **SSE Connection Handling**:
    -   `GET /sse` 엔드포인트를 통해 지속적인 연결을 수립합니다.
    -   비동기 스트림(`aiter_lines`)을 통해 서버에서 오는 이벤트를 실시간으로 청취합니다.

2.  **Session Management**:
    -   MCP 서버로부터 발급받은 `session_id`를 관리합니다.
    -   `endpoint` 이벤트를 파싱하여 메시지를 보낼 주소(Post URL)를 동적으로 획득합니다.

3.  **Method Invocation (도구 실행)**:
    -   `call_tool` 메서드는 내부적으로 `tools/call` JSON-RPC 메시지를 생성하여 서버로 전송합니다.
    -   비동기 큐(`asyncio.Queue`)를 사용하여, 요청 ID(`id`)에 맞는 응답이 올 때까지 대기(await)합니다.

#### 통신 흐름
1.  **Connect**: `GET host/sse` -> `event: endpoint` 수신 -> 세션 ID 획득
2.  **Call**: `POST host/sse/message?session_id=...` (Payload: `tools/call`)
3.  **Receive**: SSE 스트림으로 `event: message` 수신 -> 결과 큐에 매핑 -> 반환

---

## 4. 기존 방식(Proxy)과의 차이점

| 항목 | 기존 Proxy 방식 (`proxy_server.py`) | Agent Proxy 방식 (`agent_proxy_server.py`) |
| :--- | :--- | :--- |
| **실행 주체** | **Void UI** (클라이언트) | **Python Server** (백엔드) |
| **도구 실행** | UI에 [Run] 버튼 생성 후 사용자 클릭 대기 | **서버가 즉시 자동 실행** |
| **파싱 의존성** | UI의 파서가 JSON을 완벽히 이해해야 함 (깨지기 쉬움) | 서버가 유연하게 파싱 (강력한 내성) |
| **사용자 경험** | "버튼 눌러주세요" (수동적) | "제가 처리했습니다" (능동적) |

## 5. 결론 및 활용 가이드
이 아키텍처는 n8n이 보여준 **"Server-Side Execution"** 철학을 따릅니다. Void IDE와 같은 클라이언트 툴의 UI 제약사항이나 파싱 버그에 영향을 받지 않고, 언제나 안정적으로 도구를 실행할 수 있는 것이 가장 큰 장점입니다.

개발자는 `agent_proxy_server.py`를 실행해두고, `mcp_hosts_sse.py`에 필요한 도구 함수만 계속 추가하면 됩니다. 복잡한 프로토콜 규격은 이 시스템이 알아서 '통역'하고 '실행'합니다.
