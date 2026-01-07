# n8n AI Agent vs. Agent Proxy Server 구현 방식 비교 (2026-01-06)

## 1. 개요
본 문서는 n8n의 AI Agent 노드와 본 프로젝트의 `agent_proxy_server.py`가 채택하고 있는 '자율 에이전트(Autonomous Agent)' 구현 방식의 공통점과 차이점을 기술 분석합니다. 특히, LLM의 도구 사용을 강제하는 기법과 시스템적 상태 머신(State Machine)의 차이를 중점적으로 다룹니다.

---

## 2. 핵심 아키텍처 비교

### 2.1. n8n AI Agent (LangChain 기반)
- **인식 주체**: 백엔드 워크플로우 엔진 (Node-based Executor)
- **구현 방식**: 워크플로우 엔진이 LLM의 응답을 가로채어 직접 도구(노드)를 실행하고 결과를 피드백하는 **Internal Dispatcher** 구조.
- **상태 관리**: 워크플로우 실행 세션에 상태를 저장하며, LLM이 최종 답변을 내놓을 때까지 노출되지 않음.

### 2.2. Agent Proxy Dual-Module Architecture
이 시스템은 두 개의 핵심 모듈이 '뇌'와 '손'의 역할을 분담하여 자율성을 완성합니다.

- **[Brain] `agent_proxy_server.py` (Orchestrator)**:
    - n8n의 Workflow Engine과 동일한 역할을 수행.
    - 전체 루프(State Machine)를 제어하고, LLM의 생각을 해석하여 언제 어떤 도구를 쓸지 결정함.
- **[Hands] `mcp_client.py` (Interface/Driver)**:
    - n8n의 개별 커넥터(Node Driver)와 동일한 역할을 수행.
    - 실제 도구 호출을 위해 SSE 프로토콜을 처리하고, 세션을 유지하며 결과를 물리적으로 가져옴.

---

## 3. 핵심 개념: Tool Choice vs. State Machine

사용자가 제기한 "툴 호출 강제"와 "상태 머신"의 관계를 다음과 같이 정리합니다.

| 항목 | Tool Choice (채찍) | State Machine (엔진) |
| :--- | :--- | :--- |
| **정의** | LLM API 레벨에서 도구 호출을 강제하는 설정 (`required`, `auto`) | 도구 호출 후 다음 단계로 전이되는 시스템적 절차 |
| **역할** | LLM이 "말(Content)" 대신 "행동(Tool)"을 하게 함 | 툴 실행 후 그 결과를 다시 LLM에게 먹이고 재질문함 |
| **영향** | 단일 턴(Turn)의 응답 형태를 결정 | 전체 대화의 자율성 및 다단계 실행 여부를 결정 |
| **본 시스템 적용** | `tool_choice: "auto"` (필요 시 선택적 사용) | `for i in range(max_iterations)` (자율 루프 엔진) |

---

## 4. 상세 기술 비교

### 4.1. 공통점 (Autonomous Philosophy)
1.  **UI 독립성**: 클라이언트(Void IDE 등)의 [Run] 버튼이나 버튼 클릭을 기다리지 않고 서버가 주도적으로 도구를 실행함.
2.  **Native Tool Calling**: 텍스트 파싱에 의존하지 않고, 구조화된 `tool_calls` (또는 Fallback JSON) 데이터를 직접 처리함.
3.  **Context Injection**: 도구 실행 결과를 `role: "tool"`이라는 특수 역할을 부여하여 모델이 자기 행동의 결과임을 인지하게 함.

### 4.2. 차이점
- **n8n**: 시각적 노드 연결을 통해 도구 간의 흐름을 제어하며, 복잡한 에러 핸들링을 노드 레벨에서 시각화함.
- **Agent Proxy**: 코드로 작성된 루프를 통해 가장 가볍고 빠르게 동작하며, MCP(Model Context Protocol) 표준을 사용하여 외부 도구와 즉각적으로 연동됨.

---

## 5. 결론: 왜 State Machine 방식이 우월한가?
LLM에게 도구 사용을 단순히 "강제"하는 것만으로는 복잡한 문제를 해결할 수 없습니다. 
- **강제($Required$)**는 LLM에게 일을 시키는 명령일 뿐입니다.
- **상태 머신($LoopING$)**은 LLM이 일을 마칠 때까지 필요한 정보를 계속 공급해주는 **지원 시스템**입니다.

`agent_proxy_server.py`는 n8n과 동일하게 이 "지원 시스템(상태 머신)"을 내장하고 있으므로, 사용자의 개입 없이도 스스로 정보를 검색하고 분석하여 결론에 도달하는 **진정한 자율 에이전트**로서 동작합니다.
