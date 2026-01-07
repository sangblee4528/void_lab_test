# Void Lab Test 종합 가이드 (2026-01-05 기준)

## 1. 프로젝트 개요
본 프로젝트는 **Void IDE**와 **Local Ollama** 모델을 연결하고, **MCP(Model Context Protocol)** 도구를 원활하게 실행하기 위한 미들웨어 시스템입니다. 특히 Void IDE의 엄격한 UI 규격을 우회하기 위해 **"쉘 명령어 주입(Shell Command Injection)"** 방식을 채택하여, 도구 실행 버튼([Run])을 확실하게 제공합니다.

---

## 2. 시스템 아키텍처

```mermaid
flowchart LR
    Void[Void IDE] <-->|OpenAI API| Proxy[Proxy Server (8000)]
    Proxy <-->|SSE / JSON| MCP[MCP Server (3000)]
    Proxy <-->|Ollama API| Ollama[Local Ollama (11434)]
    
    subgraph "Proxy Layer"
        ProxyAdapter[Proxy Adapter]
        Note1[Shell Code Injection]
    end
    
    subgraph "Execution Layer"
        CLI[mcp_tools_runner.py]
        Tools[mcp_tools.py]
    end
    
    Proxy --"Calls (Shell Cmd)"--> CLI
    CLI --> Tools
```

## 3. 핵심 구성 요소

### 3.1. Proxy Server (`proxy_server/`)
- **역할**: Void IDE와 Ollama 사이의 중계 역할.
- **특징**:
    - **도구 감지**: LLM의 응답에서 도구 호출 의도를 파악.
    - **쉘 변환 (Plan B)**: 도구 호출 JSON을 `python mcp_tools_runner.py ...` 형태의 쉘 명령어로 변환하여 본문에 주입.
    - **스트리밍 호환**: OpenAI SSE 포맷을 준수하며 응답을 스트리밍.

### 3.2. MCP Server (`mcp_server/`)
- **역할**: 실제 비즈니스 로직(도구)을 수행.
- **주요 파일**:
    - `mcp_hosts_sse.py`: (Legacy) SSE 기반 MCP 서버 호스팅.
    - `mcp_tools.py`: `get_all_employees`, `search_docs` 등 실제 함수 정의.
    - **`mcp_tools_runner.py`**: (New) 프록시가 생성한 쉘 명령어를 받아 실제 도구를 실행하는 CLI 진입점.

### 3.3. 관리 도구 (`tools/manage_servers.py`)
- **기능**: 서버 프로세스(3000, 8000)를 조회하고 종료(Kill) 및 재시작(Restart)하는 통합 관리자.
- **실행**: `python tools/manage_servers.py`

---

## 4. 사용 방법

### 4.1. 서버 시작/재시작
가장 간편한 방법은 관리 도구를 사용하는 것입니다.

```bash
python tools/manage_servers.py
```
- 사용 중인 포트가 있으면 종료 여부를 묻습니다 (y/n).
- 정리가 끝나면 "서버를 재시작하시겠습니까?"라고 묻습니다 (y/n).
- `y`를 선택하면 **MCP Server -> (2초 대기) -> Proxy Server** 순서로 자동 실행됩니다.

### 4.2. Void IDE 연동
- **Endpoint**: `http://localhost:8000/v1`
- **Model**: `ollama-model` (또는 실제 사용 중인 모델명)
- **API Key**: `void-lab-key` (임의 값)

### 4.3. 도구 실행 테스트
채팅창에 다음과 같이 질문합니다.

> "직원 명단을 확인해줘"

**기대 결과**:
1.  모델이 "직원 명단을 확인하겠습니다" 등의 멘트를 함.
2.  그 뒤에 **쉘 코드 블록**이 나타남:
    ```bash
    python mcp_server/mcp_tools_runner.py get_all_employees '{}'
    ```
3.  코드 블록 우측 하단(또는 상단)에 **[Run]** 버튼이 생성됨.
4.  버튼 클릭 시 터미널에서 직원 목록 JSON 결과가 출력됨.

---

## 5. 주요 변경 이력 (Troubleshooting Notes)
- **2026-01-05**: Run 버튼 미표시 문제 해결을 위해 "Shell Command Injection" 전략 도입.
- **2026-01-05**: `proxy_adapter.py` 비어있는 Content 처리 보정("🛠️ 도구 호출..." 플레이스홀더).
- **2026-01-05**: `tools/manage_servers.py`에 원클릭 재시작 기능 추가.
