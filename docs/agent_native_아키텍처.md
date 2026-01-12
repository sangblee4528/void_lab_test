# Agent Native 시스템 아키텍처 문서

## 1. 개요
본 문서는 MCP(Model Context Protocol) 서버와 같은 중간 브리지 없이, LLM이 파이썬 에이전트 내부의 도구를 직접 호출하여 실행하는 **"Truly Native Agent"** 시스템의 아키텍처와 기술 명세를 다룹니다. 이 시스템은 성능 최적화와 인프라 단순화를 위해 설계되었습니다.

## 2. 시스템 구성도
전체 시스템은 에이전트 엔진과 로컬 도구 라이브러리로 구성됩니다.

| 모듈명 | 파일 위치 | 역할 | 특징 |
| :--- | :--- | :--- | :--- |
| **Native Server** | `agent_native/agent_native_server.py` | 자율 루프 제어 및 API 서빙 | Non-MCP, High Performance |
| **Native Tools** | `agent_native/native_tools.py` | 로컬 파이썬 도구 정의 및 실행 | Direct DB Access (sqlite3) |

---

## 3. 모듈별 상세 명세

### 3.1. Agent Native Server (`agent_native_server.py`)
에이전트의 **"중앙 제어 장치"**입니다. LLM의 능력을 빌려 사용자의 질문을 해결하기 위한 최적의 행동을 결정하고 즉각 실행합니다.

#### 핵심 메커니즘: Autonomous Loop (자율 반복)
1.  **Thinking**: LLM에게 `Native Tools` 목록을 포함하여 답변을 요청합니다.
2.  **Native Decision**: LLM은 Native Tool Calling 규격을 사용하여 필요한 도구와 인자를 반환합니다.
3.  **Local Execution**: 서버는 외부 네트워크 요청 없이 메모리에 로드된 `native_tools.py`의 함수를 즉시 호출합니다.
4.  **Observation**: 실행 결과(DB 데이터 등)를 대화 이력에 추가하여 다시 LLM에게 다음 판단을 맡깁니다.
5.  **Finalize**: 도구 호출이 더 이상 필요 없을 때 최종 답변을 사용자(Void IDE)에게 스트리밍합니다.

### 3.2. Native Tools (`native_tools.py`)
에이전트의 **"전문 기술 라이브러리"**입니다. 파이썬 SDK 및 드라이버를 통해 시스템 자원에 직접 접근합니다.

#### 주요 도구 목록
- `search_docs`: 회사 내부 규정 및 가이드 문서 검색 (SQLite `LIKE` 쿼리)
- `get_all_employees`: 전 직원 명단 및 기본 정보 쿼리
- `get_employee_info`: 특정 직원의 상세 인사 정보(근속일 등) 조회
- `calculate_vacation_days`: 연도별 잔여 휴가 일수 계산 로직

---

## 4. 기존 MCP 방식(`agent_proxy`)과의 비교

| 항목 | Agent Proxy (MCP 기반) | Agent Native (Truly Native) |
| :--- | :--- | :--- |
| **인프라** | 에이전트 + MCP 서버 (2개 프로세스) | **에이전트 단일 프로세스** |
| **통신** | SSE/HTTP 네트워크 통신 | **로컬 파이썬 함수 호출** |
| **속도** | 네트워크 지연 시간 발생 | **지연 시간 거의 없음 (Zero Latency)** |
| **환경 설정** | MCP 호스트 정보 등 복잡함 | **최소한의 설정으로 즉시 구동** |

---

## 5. 결론
`agent_native` 아키텍처는 "단순함이 최고의 정교함이다(Simplicity is the ultimate sophistication)"라는 원칙을 따릅니다. MCP라는 표준 규격의 유연성보다는 **성능과 직관적인 개발 환경**이 중요한 시스템에서 최적의 해답을 제공합니다.

개발자는 `native_tools.py`에 일반적인 파이썬 함수만 정의하면, 에이전트가 이를 LLM의 강력한 엔진과 연결하여 자율적으로 임무를 완수하게 됩니다.
