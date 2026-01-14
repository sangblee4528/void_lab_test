import json
import asyncio
import httpx
import logging
import sqlite3
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))

logger = logging.getLogger("mcp_loop_client")

class McpSseClient:
    """
mcp_client.py - MCP(Model Context Protocol) SSE 클라이언트 인터페이스

이 파일은 에이전트의 '도구 실행 엔진'이자 '손(Hands)' 역할을 수행합니다.
- agent_proxy_server.py(Brain)가 "도구를 실행해"라고 결정하면,
- 실제로 MCP 서버와 SSE 규격을 통해 통신하여 결과를 받아오는 통로입니다.
- SSE 연결 관리, 세션 유지, 이벤트 큐 관리 등 저수준 프로토콜 처리를 담당합니다.
"""
    
    def __init__(self, host: str, db_path: Optional[str] = None):
        self.host = host
        self.db_path = db_path
        self.session_id = None
        self.endpoint_url = None
        self._client = httpx.AsyncClient(timeout=30.0)
        self._response_queues: Dict[int, asyncio.Queue] = {}
        self._listen_task = None

    def _save_log(self, message: str, details: Optional[str] = None):
        """DB에 MCP 관련 로그 저장"""
        if not self.db_path:
            return
        try:
            # db_path가 문자열로 올 경우를 대비해 Path 객체로 변환 및 절대 경로화
            path = Path(self.db_path).resolve()
            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO agent_logs (request_id, message, details) VALUES (?, ?, ?)",
                ("MCP-SYSTEM", message, details)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"⚠️ MCP DB 로그 저장 실패: {e}")

    async def connect(self):
        """SSE 연결을 수립하고 Session ID를 획득합니다."""
        logger.info(f"📡 [MCP] SSE 연결 시도: {self.host}/sse")
        
        # 1. GET /sse 호출 (Stream 시작)
        # httpx.stream을 사용하여 지속적인 연결 유지
        self._listen_task = asyncio.create_task(self._listen_sse())
        
        # 세션 정보가 올 때까지 대기
        wait_count = 0
        while not self.session_id and wait_count < 50:
            await asyncio.sleep(0.1)
            wait_count += 1
            
        if not self.session_id:
            raise Exception("MCP 서버로부터 세션 ID를 받지 못했습니다.")
            
        logger.info(f"📡 [MCP] 연결 성공: Session ID = {self.session_id}")
        self._save_log("MCP Connection Established", f"Session ID: {self.session_id}")

    async def _listen_sse(self):
        """background에서 SSE 이벤트를 수신합니다."""
        try:
            async with self._client.stream("GET", f"{self.host}/sse") as response:
                current_event = None
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.replace("event:", "").strip()
                    elif line.startswith("data:"):
                        data_str = line.replace("data:", "").strip()
                        
                        if current_event == "endpoint":
                            # MCP 표준: endpoint 데이터는 JSON이 아닌 raw URI 문자열임
                            self.endpoint_url = data_str
                            # URL에서 session_id 추출
                            if "session_id=" in data_str:
                                self.session_id = data_str.split("session_id=")[1].split("&")[0]
                            logger.info(f"📡 [MCP] 엔드포인트 수신 (Standard URI): {self.endpoint_url}")
                        else:
                            # 다른 이벤트(예: message)는 JSON임
                            try:
                                data = json.loads(data_str)
                                if current_event == "message":
                                    msg_id = data.get("id")
                                    if msg_id in self._response_queues:
                                        await self._response_queues[msg_id].put(data)
                            except json.JSONDecodeError:
                                logger.debug(f"⚠️ [MCP] JSON 파싱 실패 (Data: {data_str})")
                        
                        current_event = None
        except Exception as e:
            logger.error(f"📡 [MCP] SSE 청취 에러: {e}")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """도구를 실행하고 결과를 기다립니다."""
        if not self.session_id:
            await self.connect()
            
        msg_id = int(asyncio.get_event_loop().time() * 1000)
        self._response_queues[msg_id] = asyncio.Queue()
        
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            },
            "id": msg_id
        }
        
        # POST /sse/message?session_id=... 호출
        url = f"{self.host}/sse/message?session_id={self.session_id}"
        
        try:
            logger.info(f"📤 [MCP REQ] 도구 호출 요청: {tool_name} (ID: {msg_id})")
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            
            # 결과 대기 (이벤트 스트림을 통해 들어옴)
            result_msg = await asyncio.wait_for(self._response_queues[msg_id].get(), timeout=20.0)
            result = result_msg.get("result", {})
            logger.info(f"📥 [MCP RESP] 응답 수신 완료 (ID: {msg_id})")
            logger.debug(f"--- [MCP RESP Detail] ---\n{json.dumps(result, ensure_ascii=False, indent=2)}\n-------------------------")
            self._save_log(f"Tool Result: {tool_name}", json.dumps(result, ensure_ascii=False))
            return result
            
        except Exception as e:
            logger.error(f"❌ [MCP] 도구 호출 실패: {e}")
            return {"error": str(e)}
        finally:
            if msg_id in self._response_queues:
                del self._response_queues[msg_id]

    async def close(self):
        if self._listen_task:
            self._listen_task.cancel()
        await self._client.aclose()
