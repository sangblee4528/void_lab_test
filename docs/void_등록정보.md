# Void IDE 등록 정보

## 1. LLM Provider 등록 (Proxy Server)

Void IDE의 **LLM/AI Provider** 설정에 등록:

```json
{
  "provider": "OpenAI Compatible",
  "name": "void_lab_test_proxy",
  "apiBase": "http://127.0.0.1:8000/v1",
  "apiKey": "not-required",
  "model": "qwen2.5:latest",
  "enabled": true
}
```

---

## 2. MCP Server 등록 (SSE 표준)

Void IDE의 **MCP Servers** 설정에 등록:

```json
{
  "mcpServers": {
    "void_lab_test_mcp": {
      "type": "sse",
      "url": "http://127.0.0.1:3000/sse",
      "description": "void_lab_test MCP 서버 (SSE)"
    }
  }
}
```

**실행**: `uvicorn mcp_hosts_sse:app --port 3000`

---

## 3. 전체 설정 요약

| 서버 | URL | 포트 | 용도 |
|------|-----|------|------|
| Proxy Server | `http://127.0.0.1:8000/v1` | 8000 | LLM API 중계 |
| MCP Host (SSE) | `http://127.0.0.1:3000/sse` | 3000 | 도구 실행 |

---

## 4. 테스트 확인 URL

```bash
# Proxy 서버 상태 확인
curl http://127.0.0.1:8000/

# MCP 서버 상태 확인  
curl http://127.0.0.1:3000/

# 도구 목록 확인
curl http://127.0.0.1:3000/tools

# SSE 연결 테스트
curl -N http://127.0.0.1:3000/sse
```
