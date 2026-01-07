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
└── docs/                      # 시스템 설계 문서
    ├── void_lab_test_설계서.md
    ├── proxy_설계서.md
    ├── mcp_설계서.md
    ├── void_등록정보.md
    └── mcp_아키텍처_비교.md