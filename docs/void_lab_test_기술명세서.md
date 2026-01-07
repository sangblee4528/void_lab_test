# Void Lab Test 기술 명세서 (Technical Specification)

## 1. 개요
본 문서는 "Void Lab Test" 프로젝트의 핵심인 **MCP (Model Context Protocol)** 서버 구축 및 **SSE (Server-Sent Events)** 통신 메커니즘, 그리고 도구 실행(Tool Execution) 구조에 대한 상세 기술 사양을 기술합니다.

### 1.1. 설계 배경: 도구 호출 파편화(Fragmentation)와 표준화
현재 LLM 생태계는 일명 **"Tool Calling 춘추전국시대"**입니다.
- **다양한 모델 규격**: OpenAI, Anthropic(Claude), Google(Gemini), 그리고 오픈소스 모델(Llama, Qwen, Ollama)이 각자 상이한 방식(JSON 객체, Markdown 블록, 인자 포맷 등)으로 도구를 호출합니다.
- **엄격한 클라이언트 요구사항**: 반면 Void IDE와 같은 클라이언트 도구는 특정 기업(주로 OpenAI)의 표준 규격을 엄격히 요구합니다. 이로 인해 모델이 의미적으로 완벽한 도구 호출을 생성하더라도, 사소한 포맷 차이로 인해 UI가 렌더링되지 않는 문제가 빈번합니다.

본 프로젝트의 **Proxy Server**는 이러한 "파편화된 모델의 출력"을 "엄격한 클라이언트 표준"으로 변환해주는 **Universal Adapter** 역할을 수행합니다. 이를 통해 사용자는 백엔드 모델(Ollama)이 무엇이든 상관없이 일관된 도구 사용 경험을 보장받을 수 있습니다.

---

## 2. MCP Server 아키텍처 (`mcp_hosts_sse.py`)

### 2.1. 설계 철학: 엔진 분리형 (Decoupled Engine)
FastAPI의 요청 처리 생명주기(Request Lifecycle)와 상관없이 지속적으로 상태를 유지하고 작업을 처리하기 위해 **Engine**과 **Transport Layer**를 분리했습니다.

- **McpEngine**: 싱글턴 백그라운드 태스크로 구동되며, 세션 관리 및 작업 분배를 담당합니다.
- **FastAPI Transport**: 클라이언트의 HTTP 요청을 받아 엔진의 큐(Queue)에 넣거나, 엔진의 출력을 SSE로 스트리밍합니다.

### 2.2. McpEngine 상세
`McpEngine` 클래스는 다음과 같은 핵심 컴포넌트를 가집니다.
*   **`input_queue`**: 모든 외부 요청(POST)이 이 큐에 쌓입니다.
*   **`sessions`**: `session_id`를 키로 하는 출력 큐(Output Queue)의 맵(Map)입니다. 각 세션별로 독립적인 SSE 스트림을 유지합니다.
*   **`run()` 루프**:
    1.  `input_queue`에서 요청을 꺼냅니다 (비동기 대기).
    2.  `payload`의 `method`를 분석하여 적절한 핸들러(`dispatch_method`)를 호출합니다.
    3.  처리 결과를 해당 세션의 출력 큐에 넣습니다.

### 2.3. SSE 엔드포인트 사양

#### 1) `GET /sse` (Connection Establishment)
*   **역할**: 클라이언트(Void, Inspector)가 MCP 서버에 연결을 맺는 진입점입니다.
*   **동작 흐름**:
    1.  고유 `session_id` (UUID) 생성.
    2.  `engine.sessions`에 해당 세션의 전용 큐 등록.
    3.  최초 이벤트로 `endpoint` 이벤트를 전송하여, 클라이언트가 메시지를 보낼 주소를 알림.
        ```
        event: endpoint
        data: http://localhost:3000/sse/message?session_id=...
        ```
    4.  이후 `message` 이벤트를 무한 루프로 대기하며 스트리밍.

#### 2) `POST /sse/message` (Message Transport)
*   **역할**: 클라이언트가 서버로 JSON-RPC 요청을 보낼 때 사용하는 통로입니다.
*   **파라미터**: `session_id` (Query String)
*   **동작**:
    1.  세션 유효성 검증.
    2.  요청 바디(JSON-RPC)를 `engine.input_queue`에 삽입(Enqueue).
    3.  즉시 `202 Accepted` 반환 (비동기 처리).

#### 3) `POST /sse` (Fallback/Handshake)
*   **역할**: Void IDE와 같이 초기 핸드쉐이크나 일부 요청을 Base URL로 직접 보내는 클라이언트를 위한 호환성 레이어.
*   **동작**: 큐를 거치지 않고 핸들러를 직접 호출하거나 엔진에 위임하여 즉시 응답을 반환.

---

## 3. 도구(Tools) 구현 명세 (`mcp_tools.py`)

### 3.1. 데이터베이스 스키마 (SQLite)
모든 도구는 로컬 SQLite DB (`db/mcp_data.db`)와 상호작용합니다.

| 테이블 | 컬럼 | 설명 |
| :--- | :--- | :--- |
| `documents` | id, title, content, category | 사내 문서 저장 |
| `employees` | id, name, department, hire_date | 직원 정보 (기본키: EMPxxx) |
| `vacations` | employee_id, year, total, used | 연차 관리 |

### 3.2. 제공 도구 목록
`TOOL_REGISTRY` 딕셔너리에 등록되어 관리됩니다.

1.  **`search_docs(query)`**: `documents` 테이블에서 `LIKE` 쿼리로 제목/내용 검색.
2.  **`get_employee_info(employee_id)`**: `employees` 테이블 단건 조회 및 근속일수 계산.
3.  **`get_all_employees()`**: 모든 직원의 ID와 이름 목록 반환.
4.  **`calculate_vacation_days(employee_id, year)`**: 총 연차 - 사용 연차 계산 로직 수행.

### 3.3. 실행 어댑터 (`execute_tool`)
*   **역할**: 도구 이름과 인자 딕셔너리를 받아 실제 함수를 호출하고, 예외 처리를 담당하는 단일 진입점.
*   **특징**: 결과는 항상 딕셔너리(`success`, `result` or `error`) 형태로 표준화되어 반환.

---

## 4. 프록시 연동 및 실행 구조 (Plan B)

### 4.1. Shell Command Injection Flow
Void IDE UI 제약을 우회하기 위해 다음과 같은 실행 흐름을 가집니다.

1.  **Proxy Server**: LLM의 응답 스트림 감시.
2.  **Adapter**: 도구 호출 JSON (`function`, `arguments`) 감지 시, 이를 가로채어(Intercept) 사용자에게 노출하지 않음.
3.  **Injection**: 대신 아래와 같은 Shell Script 블록을 본문에 삽입.
    ```bash
    python mcp_server/mcp_tools_runner.py ToolName 'JSON_ARGS'
    ```
4.  **CLI Runner (`mcp_tools_runner.py`)**:
    *   커맨드라인 인자로 도구 명과 JSON 문자열 수신.
    *   `mcp_tools` 모듈을 임포트하여 `execute_tool()` 호출.
    *   결과를 표준 출력(STDOUT)으로 Print -> 사용자가 결과 확인.

---

## 5. 통신 프로토콜 예시 (JSON-RPC over SSE)

### 초기화 (Initialize)
**Client (Request via POST):**
```json
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "void", "version": "1.0"}
  },
  "id": 1
}
```

**Server (Response via SSE):**
```
event: message
data: {"jsonrpc":"2.0","result":{"protocolVersion":"2025-03-26","capabilities":{...},"serverInfo":{...}},"id":1}
```

### 도구 목록 조회 (Tools List)
**Client:** `method: "tools/list"`
**Server:** `result: { "tools": [ { "name": "search_docs", ... }, ... ] }`

### 도구 실행 (Tool Call)
**Client:** `method: "tools/call", params: { "name": "get_employee_info", "arguments": {"employee_id": "EMP001"} }`
**Server:** `result: { "content": [ { "type": "text", "text": "{'success': true, ...}" } ] }`

---

## 6. 주요 기술적 발견 및 트러블슈팅 (Technical Lessons)
프로젝트 진행 중 발견된 주요 기술적 이슈와 해결 과정에서 얻은 인사이트를 정리합니다.

### 6.1. MCP 서버 상태 표시 (Red/Blue/Green Light)의 진실
초기 개발 시 MCP 서버를 등록해도 계속 **빨간불(Red Light)**이 뜨거나 연결되지 않는 문제가 있었습니다.
*   **원인**: 단순한 HTTP 200 OK 응답만으로는 연결 상태가 "정상"으로 간주되지 않습니다.
*   **해결**: SSE 프로토콜의 전체 생명주기(Lifecycle)를 구현해야만 **파란불/초록불(Green Light)**이 들어옵니다.
    1.  클라이언트가 `GET /sse` 연결.
    2.  서버가 `event: endpoint`를 전송.
    3.  서버가 `event: message` 스트림을 열어두고 Keep-Alive 상태 유지.
    *   이 3단계가 완료되어야 Void는 "서버가 살아있고 통신 가능하다"고 판단합니다.

### 6.2. UI 렌더링과 "Shell Injection" 선택 이유
Ollama와 같은 로컬 모델은 `tool_calls` JSON 규격을 준수하더라도 미묘한 차이(인용부호, 공백, 필드 순서 등)가 있습니다.
*   **문제**: Void IDE는 이러한 미세한 차이에도 민감하게 반응하여, 도구 실행 버튼을 렌더링하지 않거나 메시지를 숨기는 현상이 발생했습니다.
*   **결정**: 모델의 출력을 완벽하게 OpenAI 규격으로 맞추는 것은 불가능에 가깝다고 판단(모델 자체의 특성), 대신 **"Shell Command Injection"** 전략을 채택했습니다. 이는 UI 의존성을 제거하고, 터미널 실행이라는 가장 보편적인 인터페이스를 활용함으로써 100%의 실행 보장성을 확보한 결정입니다.
