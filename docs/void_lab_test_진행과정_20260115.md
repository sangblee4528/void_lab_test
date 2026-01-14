# Void Lab Test 진행 과정 정리 (2026-01-15)

본 문서는 `agent_native` 서버 개발 및 윈도우 환경 테스트 중 발생한 이슈와 수정 사항을 정리한 기록입니다.

## 1. 주요 수정 사항 및 이슈 해결

### 1-1. 405 Method Not Allowed 에러 해결
*   **현상**: `/v1/chat/completions` 호출 시 405 에러 발생.
*   **원인**: 해당 엔드포인트는 OpenAI 규격에 따라 `POST`만 지원하나, `GET` 요청이 인입됨.
    *   **윈도우 특이점**: PowerShell의 `curl` 명령어가 실제 `curl.exe`가 아닌 `Invoke-WebRequest`의 별칭(Alias)으로 동작하여 파라미터 해석 오류로 인해 `GET`으로 요청되는 현상 확인.
*   **조치**:
    *   `GET` 요청 시 친절한 안내 메시지(POST 사용 가이드)를 반환하는 핸들러 추가.
    *   서버 상태를 즉시 확인할 수 있는 루트(` / `) 엔드포인트 도입.
    *   사용자에게 `curl.exe` 또는 파워쉘 전용 명령어를 사용하도록 가이드 제공.

### 1-2. 500 Internal Server Error (RemoteProtocolError) 대응
*   **현상**: `POST` 요청은 전달되나, LLM(Ollama) 호출 단계에서 `RemoteProtocolError` 발생.
*   **원인**: Ollama 서버가 응답 없이 연결을 끊음 ("Empty reply from server").
    *   **진단 결과**: 포트 `11434`가 Docker(`com.docker.backend.exe`) 또는 WSL에 의해 점유되어 있으나, 실제 Ollama 서비스가 응답하지 않는 상태로 분석됨.
*   **조치**:
    *   서버 루트(` / `) 엔드포인트에 **Ollama 연결 상태 진단 기능** 추가.
    *   `call_llm` 함수 내 상세 에러 로깅 추가 (연결 끊김 시 원인 분석 가이드 출력).

### 1-3. 코드 안정성 및 버그 수정
*   **현상**: 서버 재시작 시 `NameError: name 'ChatRequest' is not defined` 발생.
*   **원인**: 코드 업데이트 과정에서 `ChatRequest` 클래스 정의가 실수로 누락됨.
*   **조치**: `agent_native_server.py` 및 `agent_native_loop_server.py` 파일의 모델 정의부 복구 완료.

## 2. 세부 소스 코드 수정 내역

| 구분 | 주요 수정 내용 (기술적 상세) | 관련 파일 |
| :--- | :--- | :--- |
| **상태 진단** | 루트(`/`) 엔드포인트에 `httpx`를 이용한 Ollama 서버 연동 테스트 로직 추가 | `agent_native_server.py`, `agent_native_loop_server.py` |
| **에러 핸들링** | `call_llm` 함수 내 `httpx.RemoteProtocolError` 예외 처리 및 상세 가이드 로그 출력 | 두 서버 파일 공통 |
| **가이드 추가** | `app.get("/v1/chat/completions")` 핸들러 추가로 POST 전용임을 알림 | 두 서버 파일 공통 |
| **모델 복구** | `pydantic.BaseModel`을 상속받은 `ChatRequest` 클래스 정의 원복 | 두 서버 파일 공통 |
| **가독성 개선** | 중복된 `headers` 변수 초기화 제거 및 `Content-Type` 명시 | 두 서버 파일 공통 |

## 3. 현재 상태 및 향후 계획

### 현재 상태
*   서버측 수정은 완료되었으며, 진단 도구(루트 엔드포인트)가 준비됨.
*   Ollama 서버가 비정상 응답을 보내고 있어, 사용자 측의 Ollama 서비스 점검이 필요한 상태.

### 향후 계획
*   [ ] 사용자의 Ollama 서비스(Docker/WSL/Native) 정상 실행 확인.
*   [ ] 루트 엔드포인트(`http://127.0.0.1:8001/`)를 통한 `llm_connection: connected` 상태 확인.
*   [ ] 최종 비즈니스 로직(직원 명단 조회 등) 정상 동작 테스트.

---
**기록자**: Antigravity (AI Assistant)
**날짜**: 2026-01-15 (사용 요청 기준)
