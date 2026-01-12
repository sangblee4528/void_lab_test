void_lab_test/
├── proxy_server/              # LLM 통신 중계 및 규격 변환
│   ├── proxy_server.py        # 메인 서버 (FastAPI)
│   ├── proxy_adapter.py       # 모델별 호출 규격 변환 로직
│   ├── inventory.py           # LLM에 주입할 툴 인벤토리 관리
│   └── proxy_config/
│       └── proxy_config.json  # Ollama 연결 및 포트 정보
├── mcp_server/                # 실제 도구(Tool) 실행부
│   ├── mcp_hosts_sse.py       # MCP 표준 SSE 서버
│   ├── mcp_tools.py           # 실제 실행될 개별 도구 정의
│   └── mcp_config/
│       └── mcp_config.json    # DB 연결 및 MCP 설정 정보
├── agent_native/               # 독자적 에이전트 (Non-MCP)
│   ├── agent_native_server.py  # 메인 서버 (Truly Native)
│   ├── native_tools.py         # 내장 네이티브 도구 정의
│   └── agent_native_config/
│       └── agent_native_config.json
├── agent_proxy/                # 자율 에이전트 (MCP 기반)
│   ├── agent_proxy_server.py   # 메인 서버 (Proxy)
│   ├── mcp_client.py           # MCP 통신 클라이언트
│   └── agent_proxy_config/
│       └── agent_proxy_config.json
├── db/                         # 공통 데이터베이스
│   ├── mcp_data.db             # 직원/문서 정보 (공통)
│   ├── agent_proxy_data.db     # 프록시 에이전트 로그
│   └── agent_native_data.db    # 네이티브 에이전트 로그
├── tools/                      # 프로젝트 관리 도구
│   └── manage_servers.py       # 서버 통합 구동 관리 (Native 지원)
└── docs/                      # 시스템 설계 및 진행 기록 (상기 참조)
    ├── void_lab_test_설계서.md
    ├── proxy_설계서.md
    ├── mcp_설계서.md
    ├── void_등록정보.md
    ├── mcp_아키텍처_비교.md
    ├── agent_native_아키텍처.md
    ├── 질문_native_흐름도.md
    ├── void_lab_test_진행과정_20260112.md
    └── void_lab_test_종합_가이드.md