# Agent Loop API 아키텍처 및 상세 설계

본 문서는 **클라이언트 기반 REST API 승인 방식**을 채택한 `agent_loop_api` 시스템의 아키텍처와 동작 흐름을 설명합니다.

---

## 1. 시스템 아키텍처

클라이언트(Client)가 도구 실행 권한을 가지며, 서버(Server)는 도구 실행 의도를 파악하여 승인을 요청하는 구조입니다.

### 전체 구성도

```mermaid
graph TD
    Client[Client / Void IDE] -->|1. Chat Request| Server[Agent Loop API Server]
    Server -->|2. LLM Call| LLM[Ollama (LLM)]
    LLM -->|3. Tool Calls Detected| Server
    Server -->|4. Pending Response| Client
    Client -->|5. Approval Request| Server
    Server -->|6. Execute Tool| Tools[Native Tools]
    Tools -->|7. Query| DB[(SQLite DB)]
    Tools -->|8. Result| Server
    Server -->|9. Final LLM Call| LLM
    Server -->|10. Final Response| Client
```

---

## 2. 상세 흐름 및 코드 매핑

사용자가 "직원 목록을 보여줘"라고 요청했을 때의 내부 처리 과정을 코드 레벨에서 상세히 추적합니다.

### Step 1: 채팅 요청 (Chat Request)
**Client → Server** (`POST /v1/chat/completions`)

- **파일**: `agent_loop_api_routes.py`
- **함수**: `chat_completions(request: ChatRequest)`
- **동작**:
    1. 요청을 받고 `generate_request_id()`로 고유 ID 생성
    2. `call_llm()`을 호출하여 LLM에게 질문 전달

### Step 2: 도구 호출 감지 (Tool Detection)
**Server ↔ LLM**

- **파일**: `agent_loop_api_routes.py`
- **함수**: `detect_tool_calls(assistant_msg)`
- **동작**:
    1. LLM이 `tool_calls` 필드나 JSON 텍스트로 `get_all_employees` 호출 의도를 반환
    2. 서버가 이를 감지하면 **즉시 실행하지 않고** 멈춤

### Step 3: 승인 대기 처리 (Pending)
**Server → Client**

- **파일**: `agent_loop_api_routes.py`
- **함수**: `chat_completions` 내부 로직
- **동작**:
    1. `PendingApproval` 객체 생성 (상태: `pending`)
    2. `save_pending_to_db()` 호출하여 DB의 `pending_requests` 테이블에 저장
    3. 클라이언트에게 `approval_required: true`와 `request_id`가 포함된 응답 반환

### Step 4: 승인 요청 (Approve)
**Client → Server** (`POST /v1/approve/{request_id}`)

- **파일**: `agent_loop_api_routes.py`
- **함수**: `approve_request(request_id)`
- **동작**:
    1. `get_pending_from_db()`로 대기 중인 요청 조회
    2. 사용자가 승인했으므로 도구 실행 루프 시작

### Step 5: 도구 실행 (Tool Execution)
**Server → Tool → DB**

- **파일**: `agent_loop_api_routes.py`
- **로직**: `TOOL_REGISTRY`에서 함수 조회 및 실행
- **매핑된 함수**: `agent_loop_api_tools.py`의 `get_all_employees()`
    ```python
    def get_all_employees() -> Dict[str, Any]:
        # SQLite DB 연결 및 쿼리 실행
        cursor.execute("SELECT ... FROM employees")
    ```

### Step 6: 최종 응답 생성 (Final Response)
**Server ↔ LLM**

- **파일**: `agent_loop_api_routes.py`
- **동작**:
    1. 도구 실행 결과(`employees` 리스트)를 메시지 이력에 추가 (`role: tool`)
    2. `call_llm()`을 다시 호출하여 최종 답변 생성
    3. `update_pending_status()`로 상태를 `completed`로 변경
    4. 클라이언트에게 최종 결과 반환

---

## 3. 핵심 파일 및 함수 참조

| 파일명 | 주요 역할 | 주요 함수/클래스 |
|--------|-----------|------------------|
| `agent_loop_api_server.py` | 메인 서버 진입점 | `app` (FastAPI), `lifespan` (시작/종료) |
| `agent_loop_api_routes.py` | API 비즈니스 로직 | `chat_completions`, `approve_request`, `detect_tool_calls` |
| `agent_loop_api_tools.py` | 도구 구현체 | `get_all_employees`, `init_database` |
| `agent_loop_api_models.py` | 데이터 모델 | `ChatRequest`, `PendingApproval`, `ApprovalStatus` |
| `test_loop_api.py` | 테스트 클라이언트 | `chat`, `approve`, `reject` (대화형 테스트) |

---

## 4. 데이터베이스 스키마

### `pending_requests` (승인 대기 관리)
| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| `request_id` | TEXT (PK) | 요청 고유 ID (예: `req_20260114...`) |
| `tool_calls` | TEXT (JSON) | 실행하려는 도구 정보 |
| `messages` | TEXT (JSON) | 현재까지의 대화 이력 |
| `status` | TEXT | `pending`, `approved`, `rejected`, `completed` |
| `result` | TEXT (JSON) | 최종 실행 결과 |

### `employees` (예제 데이터)
| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| `id` | INTEGER (PK) | 직원 ID |
| `name` | TEXT | 이름 |
| `department`| TEXT | 부서 |
| `position` | TEXT | 직책 |

---

## 5. 실행 및 테스트 가이드

### 5-1. 서버 실행

터미널을 열고 `agent_loop_api` 디렉토리로 이동하여 서버를 실행합니다.

```bash
cd agent_loop_api
python agent_loop_api_server.py
```
성공 시: `Uvicorn running on http://127.0.0.1:8012`

### 5-2. 테스트 방법 (3가지)

#### 방법 A: Python 테스트 클라이언트 (권장)
대화형 인터페이스로 채팅과 승인을 쉽게 테스트할 수 있습니다.

```bash
python test_loop_api.py
```
- `/pending`: 대기 목록 확인
- `/quit`: 종료

#### 방법 B: 자동 검증 스크립트
전체 흐름(요청→대기→승인→결과)을 자동으로 테스트합니다.

```bash
python verify_api_flow_clean.py
```

#### 방법 C: CMD에서 curl 사용 (수동 테스트)

**1. 채팅 요청 (승인 대기 유도)**
```cmd
curl.exe -X POST http://127.0.0.1:8012/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\": \"qwen2.5-coder:7b\", \"messages\": [{\"role\": \"user\", \"content\": \"직원 목록 보여줘\"}], \"stream\": false}"
```
응답에서 `"approval_required": true`와 `"request_id": "req_..."`를 확인하세요.

**2. 대기 목록 확인**
```cmd
curl.exe http://127.0.0.1:8012/v1/pending
```

**3. 승인 요청**
위에서 확인한 `request_id`를 URL에 넣어서 실행합니다.
```cmd
curl.exe -X POST http://127.0.0.1:8012/v1/approve/req_2026xxxxxxxxx
```
성공 시 최종 답변(직원 명단)이 반환됩니다.


