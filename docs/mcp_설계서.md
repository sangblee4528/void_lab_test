# MCP 서버 설계서 (SSE Transport Specification)

본 문서는 `mcp_hosts_sse.py` 서버의 구현 상세와 MCP(Model Context Protocol) 표준 규격 준수 사항을 정리합니다. 특히 Void IDE와 같은 엄격한 클라이언트와의 호환성을 위한 핵심 설계를 강조합니다.

## 1. SSE 전송 계층 (SSE Transport)

MCP 표준 규격에 따른 SSE(Server-Sent Events) 연결 및 세션 관리 방식입니다.

### 1.1 초기 연결 (Handshake)
- **주소**: `GET http://127.0.0.1:3000/sse`
- **프로세스**: 
  1. 클라이언트가 GET 요청 시 서버는 새로운 `session_id`를 생성합니다.
  2. 연결 즉시 서버는 `endpoint` 이벤트를 발생시켜 메시지 전송용 URL을 고지합니다.
  
### 1.2 핵심 사양: Endpoint 이벤트 (CRITICAL)
Void IDE와 같은 클라이언트에서 `SyntaxError`를 방지하기 위해 반드시 지켜야 할 사항입니다.
- **이벤트 이름**: `endpoint`
- **데이터 형식**: **순수 URI 문자열 (Plain Text URI)**
  - ❌ 잘못된 예: `data: {"url": "http://...", "session_id": "..."}` (JSON)
  - ✅ 올바른 예: `data: http://127.0.0.1:3000/sse/message?session_id=UUID_STRING`
- **이유**: 표준 MCP SDK는 `data` 필드 전체를 그대로 URI 주소로 인식하여 이후 `POST` 요청을 보내기 때문입니다.

---

## 2. 메시지 전송 로직

### 2.1 메시지 포스트 (Message Posting)
- **주소**: `POST http://127.0.0.1:3000/sse/message?session_id=...`
- **규격**: JSON-RPC 2.0
- **역할**: 클라이언트가 서버에 도구 목록 요청(`tools/list`)이나 도구 실행(`tools/call`) 명령을 보낼 때 사용합니다.

### 2.2 초기화 핸드쉐이크 (Initialize)
일부 클라이언트는 SSE 스트림을 열기 전이나 직후에 기본 `/sse` 경로로 `POST` 요청을 보내 서버의 가용성을 확인합니다.
- **핸들러**: `@app.post("/sse")`
- **응답**: `initialize` 메서드에 대해 서버 정보 및 프로토콜 버전(`2025-03-26`)을 포함한 정규 JSON-RPC 결과 반환.

---

## 3. 프로토콜 사양 (Protocol Version)

- **지원 버전**: `2025-03-26` (Void IDE 최신 요구 사항)
- **호환성**: 서버 응답의 `protocolVersion` 필드를 클라이언트가 요청한 버전과 일치시켜 '빨간불(연결 에러)'을 방지합니다.

## 4. 보안 및 CORS

- **CORS 설정**: 브라우저 기반 IDE(Void 등)의 접근을 위해 `allow_origins`, `allow_methods`, `allow_headers`를 모두 `*`로 개방하여 `Preflight` 요청 문제를 해결합니다.

---
**업데이트 날짜**: 2026-01-04
**핵심 변경 사항**: SSE Endpoint 데이터 형식을 JSON에서 Plain URI로 수정하여 SyntaxError 해결.
