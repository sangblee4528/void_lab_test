시니어 시스템 엔지니어로서, 분석하시기에 가장 최적화된 구조로 **`void_lab_test` 상세 데이터 시퀀스**를 마크다운(`.md`) 형식으로 정리해 드립니다.

이 문서는 각 단계별 데이터의 흐름과 시스템 엔지니어가 로그를 통해 검증해야 할 '관전 포인트'를 명확히 구분하여 작성되었습니다.

---

# 🏗️ [Design] void_lab_test 상세 데이터 시퀀스

본 시퀀스는 **Void(IDE)** 내부의 **Chat UI** 모듈과 **MCP Client** 모듈이 어떻게 상호작용하며 로컬 인프라(Proxy, Ollama, MCP Host)와 통신하는지 분석하기 위한 가이드입니다.

---

## 🔄 1. 전체 데이터 흐름 시퀀스 (Step-by-Step)

### **1단계: 질문 접수 및 컨텍스트 준비 (Context Assembly)**

* **User → Void (Chat UI)**: 사용자가 채팅창에 "신입 사원 휴가 규정 알려줘" 입력.
* **Void (Chat UI) ↔ Void (MCP Client)**: 채팅 모듈이 MCP 클라이언트에 "현재 등록된 `mcp_hosts.py`에서 사용 가능한 툴 목록(Metadata) 가져와" 요청.
* **Void (Chat UI)**: [사용자 질문 + 툴 목록(인벤토리)]을 하나의 JSON 패키지로 조립.

### **2단계: LLM 판단 요청 및 중계 (Inference & Proxying)**

* **Void (Chat UI) → Proxy_Server**: 조립된 패키지를 `http://127.0.0.1:8000`으로 전송.
* **Proxy_Server (Logging)**:
> **🔍 분석 포인트 1**: Void가 보낸 툴 명세와 질문 내용이 규격에 맞는지 확인. 필요시 `proxy_adapter.py`를 통해 Ollama 규격으로 변환.


* **Proxy_Server → Ollama**: 비동기(`httpx`)로 Ollama(Qwen 2.5)에게 전달.

### **3단계: LLM의 도구 사용 의도 수신 (Intent Detection)**

* **Ollama → Proxy_Server**: 질문 분석 후 `tool_calls` JSON 반환. (예: `search_docs(query='신입 사원 휴가')`)
* **Proxy_Server (Logging)**:
> **🔍 분석 포인트 2**: LLM이 올바른 툴 이름과 파라미터를 추출했는지 로그 확인.


* **Proxy_Server → Void (Chat UI)**: LLM의 실행 의도를 다시 Void로 반환.

### **4단계: 실제 도구 실행 명령 (Tool Execution)**

* **Void (Chat UI) → Void (MCP Client)**: "LLM이 이 툴을 쓰라는데? 실행해줘."
* **Void (MCP Client) → mcp_hosts.py**: `http://127.0.0.1:3000`으로 표준 JSON-RPC 호출 전달.
* **mcp_hosts.py (Logging)**:
> **🔍 분석 포인트 3**: Void로부터 정식 JSON-RPC 요청이 들어왔는지 로그 확인.


* **mcp_hosts.py ↔ mcp_tools.py**: 실제 파이썬 함수를 실행하여 데이터(DB/파일) 확보.

### **5단계: 실행 결과 피드백 (Data Feedback)**

* **mcp_tools.py → mcp_hosts.py → Void (MCP Client)**: 실행 결과값(예: "입사 1년 미만은 월 1회...") 반환.
* **Void (MCP Client) → Void (Chat UI)**: 확보된 데이터를 채팅 모듈로 전달.
* **Void (Chat UI)**: "자, 툴 결과가 왔으니 이제 답변을 완성하라고 LLM에게 다시 보내자."

### **6단계: 최종 답변 생성 및 출력 (Augmentation & Generation)**

* **Void (Chat UI) → Proxy_Server → Ollama**: [원래 질문 + 툴 실행 결과 데이터]를 묶어서 재질문.
* **Ollama → Proxy_Server**: 데이터를 바탕으로 자연스러운 최종 답변 생성.
* **Proxy_Server → Void (Chat UI)**: 최종 답변 중계.
* **Void (Chat UI) → User**: 채팅창에 최종 결과물 렌더링.

---

## 📊 2. 컴포넌트별 분석 포인트 요약

| 구성 요소 | 핵심 역할 | 시스템 엔지니어의 디버깅 포인트 |
| --- | --- | --- |
| **Void (Chat UI)** | **매니저** | 전체 대화 턴(Turn) 관리 및 LLM과 사용자 간 중계 |
| **Void (MCP Client)** | **브릿지** | MCP 표준 규격(JSON-RPC)을 준수하며 `mcp_hosts.py`와 통신 |
| **Proxy_Server** | **통역사/감시자** | LLM 요청 규격 보정 및 통신 패킷 전수 로깅 |
| **mcp_hosts.py** | **워커(Worker)** | 실제 시스템 권한을 가지고 물리적 작업을 수행 |

---

## 💡 시니어의 조언

이 시퀀스의 핵심은 **"데이터가 어디서 유턴하는가"**입니다. LLM(Ollama)은 직접 툴을 실행할 수 없으므로, 모든 실행 권한은 **Void(MCP Client)**가 가지고 있습니다. 분석 시 `Proxy_Server`에서 나가는 요청과 `mcp_hosts.py`로 들어오는 요청의 타임스탬프를 비교해 보면 전체 레이턴시(Latency)를 파악할 수 있습니다.

---

**"이 문서가 분석의 이정표가 되길 바랍니다. 이제 실험 환경 구축의 첫 코드로 `proxy_server/proxy_server.py`의 비동기 베이스 코드를 생성해 드릴까요?"** 다음 단계를 알려주세요!