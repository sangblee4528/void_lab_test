"""
mcp_hosts_sse.py - SSE 방식 MCP 서버 (엔진 분리형)

Void의 빈번한 재연결에도 안정적으로 동작하도록 
엔진 실행부와 SSE 연결부를 완전히 분리한 구조입니다.
"""

import json
import logging
import sys
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
 # 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))
from typing import Dict, Any, List, Optional, AsyncGenerator

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# 로컬 모듈 임포트
from mcp_tools import execute_tool, ensure_database

# 설정 경로
CONFIG_PATH = Path(__file__).parent / "mcp_config" / "mcp_config.json"

def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"⚠️ 설정 파일 로드 실패 (기본값 사용): {e}")
        return {
            "mcp": {"host": "127.0.0.1", "port": 3000}
        }

config = load_config()

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("mcp_hosts_sse")

# ============================================================
# ⚙️ MCP Engine (Singleton Background Task)
# ============================================================
# 🚀 MCP Engine (Singleton Background Task)
# ============================================================
class McpEngine:
    def __init__(self):
        self.input_queue = asyncio.Queue()
        self.sessions: Dict[str, asyncio.Queue] = {}
        self.is_running = False

    async def run(self):
        """서버 시작 시 단 한 번 실행되는 메인 엔진 루프"""
        self.is_running = True
        logger.info("⚙️ [Engine] MCP 엔진 루프 시작")
        
        while self.is_running:
            try:
                # 큐에서 작업 대기 (종료 체크를 위해 타임아웃 적용)
                try:
                    request_data = await asyncio.wait_for(self.input_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                    
                session_id = request_data.get("session_id")
                payload = request_data.get("payload")
                
                method = payload.get("method")
                request_id = payload.get("id")
                
                logger.info(f"⚙️ [Engine] 작업 처리 시작: {method} (Session: {session_id})")
                
                # 실제 도구 실행 또는 메서드 처리
                result = await self.dispatch_method(method, payload.get("params", {}))
                
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id
                }
                
                # 해당 세션의 출력 큐로 결과 전달
                if session_id in self.sessions:
                    await self.sessions[session_id].put(response)
                    logger.info(f"⚙️ [Engine] 결과 전송 완료 (Session: {session_id})")
                else:
                    logger.warning(f"⚙️ [Engine] 세션을 찾을 수 없음: {session_id}")
                
                self.input_queue.task_done()
                
            except Exception as e:
                logger.error(f"⚙️ [Engine] 루프 에러: {e}")
                await asyncio.sleep(1)

    async def dispatch_method(self, method: str, params: Dict[str, Any]) -> Any:
        """비즈니스 로직 처리"""
        if method == "initialize":
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "logging": {},
                    "resources": {"subscribe": True, "listChanged": True},
                    "prompts": {"listChanged": True}
                },
                "serverInfo": {"name": "void_lab_test_mcp_sse", "version": "1.0.1"}
            }
        elif method == "tools/list":
            return {"tools": get_tool_definitions()}
        elif method == "tools/call":
            raw_result = execute_tool(params.get("name"), params.get("arguments", {}))
            # [MCP 표준] 결과를 'content' 배열 내의 'text' 타입으로 포장합니다.
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(raw_result, ensure_ascii=False, indent=2)
                    }
                ]
            }
        elif method == "notifications/initialized":
            return None # Notification은 결과가 필요 없음
        return {"error": "Method not found"}

# 엔진 인스턴스 생성
engine = McpEngine()

# ============================================================
# 📡 SSE Transport Layer
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 초기화 및 종료 시 정리"""
    ensure_database()
    # 서버 시작 시 엔진을 백그라운드 태스크로 실행 (선행 실행)
    task = asyncio.create_task(engine.run())
    logger.info("🚀 MCP 서버 및 엔진 초기화 완료")
    yield
    # 종료 시 정리
    engine.is_running = False
    await task
    logger.info("👋 MCP 서버 종료")

app = FastAPI(
    title="Void Lab Test - MCP Host Server (SSE)",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/tools")
async def list_tools():
    """도구 목록 조회 (Discovery용)"""
    return {"tools": get_tool_definitions()}

@app.get("/sse")
async def sse_connect(request: Request):
    """클라이언트의 SSE 연결 시도를 처리합니다."""
    logger.info(f"📡 [SSE] incoming GET request to /sse")
    session_id = str(uuid.uuid4())
    session_queue = asyncio.Queue()
    engine.sessions[session_id] = session_queue
    
    logger.info(f"📡 [SSE] 새 연결 수립: {session_id}")
    
    async def event_generator():
        # 1. 연결 성공 및 세션 정보 전송
        # 1. 연결 성공 및 세션 정보 전송 (MCP 표준: data는 반드시 URI 형태여야 함)
        endpoint_url = f"http://127.0.0.1:3000/sse/message?session_id={session_id}"
        logger.info(f"📡 [SSE] Sending endpoint event: {endpoint_url}")
        yield f"event: endpoint\ndata: {endpoint_url}\n\n"
        
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    # 엔진이 처리한 결과를 큐에서 꺼내서 전송
                    message = await asyncio.wait_for(session_queue.get(), timeout=20.0)
                    yield f"event: message\ndata: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive
                    yield ": keep-alive\n\n"
        finally:
            if session_id in engine.sessions:
                del engine.sessions[session_id]
            logger.info(f"📡 [SSE] 연결 종료 및 세션 정리: {session_id}")

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

@app.post("/sse")
async def sse_post_debug(request: Request):
    """Void가 /sse에 POST를 보낼 경우를 대비한 핸들러 (Handshake 대응)"""
    try:
        body = await request.json()
        method = body.get("method")
        request_id = body.get("id")
        
        logger.info(f"⚠️ [SSE-POST] /sse에 POST 수신됨: {method} (ID: {request_id})")
        
        if method == "initialize":
            # Void IDE의 초기화 요청에 대한 정규 응답 반환
            # 클라이언트(Void)가 요청한 protocolVersion(2025-03-26)과 일치시킵니다.
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "void_lab_test_mcp_sse_compat", "version": "1.0.3"}
                }
            }
        elif method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}} # OK
        elif method == "tools/list":
            # 세션이 아직 완전히 맺어지지 않은 상태에서 요청이 올 경우를 대비
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": get_tool_definitions()}
            }
        elif method == "tools/call":
            # 실제 도구 실행 루틴 호출
            logger.info(f"🛠️ [SSE-POST] 도구 실행 요청: {body.get('params', {}).get('name')}")
            result = await engine.dispatch_method("tools/call", body.get("params", {}))
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        
        logger.warning(f"❓ [SSE-POST] 처리되지 않은 메서드: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method {method} not found on base SSE URL"}}
        
    except Exception as e:
        body = await request.body()
        logger.error(f"❌ [SSE-POST] 처리 중 에러: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/sse/message")
async def sse_message(request: Request):
    """클라이언트의 요청을 엔진 큐에 넣는 역할만 수행"""
    session_id = request.query_params.get("session_id")
    if not session_id or session_id not in engine.sessions:
        logger.error(f"📨 [POST] 유효하지 않은 세션 ID: {session_id}")
        raise HTTPException(status_code=400, detail="Invalid Session")
        
    try:
        payload = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    logger.info(f"📨 [POST] 요청 수신: {payload.get('method')} (Session: {session_id})")
    logger.debug(f"📨 [POST] 페이로드 상세: {json.dumps(payload, ensure_ascii=False)}")
    
    # 엔진 입력 큐에 작업 추가
    await engine.input_queue.put({
        "session_id": session_id,
        "payload": payload
    })
    
    return {"status": "accepted"}

def get_tool_definitions():
    return [
        {
            "name": "search_docs",
            "description": "회사 문서에서 정보를 검색합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 키워드"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_employee_info",
            "description": "직원 정보를 조회합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "직원 ID"}
                },
                "required": ["employee_id"]
            }
        },
        {
            "name": "get_all_employees",
            "description": "모든 직원의 목록을 조회합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "calculate_vacation_days",
            "description": "직원의 남은 휴가 일수를 계산합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "직원 ID"},
                    "year": {"type": "integer", "description": "조회할 연도"}
                },
                "required": ["employee_id"]
            }
        }
    ]

if __name__ == "__main__":
    import uvicorn
    host = config["mcp"]["host"]
    port = config["mcp"]["port"]
    logger.info(f"🚀 [FastAPI] 서버 시작 시도: {host}:{port}")
    uvicorn.run(app, host=host, port=port)
