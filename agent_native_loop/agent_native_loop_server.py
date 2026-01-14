"""
# agent_native_loop_server.py - 자율적으로 도구를 실행하는 능동적 대리인 서버 (Native 버전)

LLM이 도구 호출을 요청하면, 클라이언트(Void)에게 반환하기 전에 
직접 MCP 서버와 통신하여 도구를 실행하고 결과를 LLM에게 다시 전달합니다.
최종 답변이 나올 때까지 이 과정을 반복합니다.
"""

import json
import logging
import sys
import sqlite3
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel

# 로컬 모듈
# 스크립트 위치를 경로에 추가하여 어디서 실행하든 native_tools를 찾을 수 있게 함
sys.path.append(str(Path(__file__).parent))
from native_loop_tools import NATIVE_TOOL_DEFS, NATIVE_TOOL_REGISTRY

# 설정 로드
CONFIG_PATH = (Path(__file__).parent / "agent_native_loop_config" / "agent_native_loop_config.json").resolve()

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
        
    # 프로파일 지원: active_profile이 있으면 해당 설정을 llm 섹션으로 복사
    if "active_profile" in config and "llm_profiles" in config:
        active = config["active_profile"]
        if active in config["llm_profiles"]:
            config["llm"] = config["llm_profiles"][active]
            
    return config

config = load_config()

# 로깅 설정
LOG_FILE = (Path(__file__).parent / "agent_native_loop.log").resolve()
logging.basicConfig(
    level=getattr(logging, config["logging"]["level"]),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("agent_native_loop")
# mcp_client 로거도 같은 핸들러를 사용하도록 설정 (상속)
logging.getLogger("mcp_loop_client").setLevel(getattr(logging, config["logging"]["level"]))

# DB 경로 해결 (상대 경로를 절대 경로로 변환)
DB_RELATIVE_PATH = config.get("database", {}).get("path", "../db/agent_native_loop_data.db")
DB_PATH = (Path(__file__).parent / "agent_native_loop_config" / DB_RELATIVE_PATH).resolve()

# MCP 클라이언트 제거 (로컬 도구 사용)
# mcp_client = McpSseClient(config["mcp"]["host"], db_path=DB_PATH)

def save_agent_log(request_id: str, message: str, details: Optional[str] = None):
    """DB에 에이전트 활동 로그 저장"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agent_logs (request_id, message, details) VALUES (?, ?, ?)",
            (request_id, message, details)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"⚠️ DB 로그 저장 실패: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 초기화"""
    logger.info("🤖 Agent Native Server 시작 중 (Truly Native Mode)...")
    logger.info(f"✅ {len(NATIVE_TOOL_DEFS)}개의 네이티브 도구 로드 완료")
    yield
    logger.info("👋 Agent Native Server 종료")

app = FastAPI(title="Void Lab Test - Active Agent Native", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

# 요청 모델
class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    tools: Optional[List[Dict[str, Any]]] = None
    stream: bool = False

@app.get("/v1/models")
async def list_models():
    """사용 가능한 모델 목록 반환 (Void IDE 초기화 대응)"""
    return {
        "object": "list",
        "data": [
            {
                "id": config["llm"]["model"],
                "object": "model",
                "created": int(datetime.now().timestamp()),
                "owned_by": config["llm"]["provider"]
            }
        ]
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    자율 실행 루프를 포함한 채팅 엔드포인트
    """
    request_id = datetime.now().strftime("%H%M%S")
    logger.info(f"📥 [Agent-{request_id}] 새 요청 수신: {request.messages[-1].content}")
    save_agent_log(request_id, "Request Received", request.messages[-1].content)
    
    try:
        current_messages = [msg.model_dump(exclude_none=True) for msg in request.messages]
        
        # 도구 목록 로드
        tools = request.tools if request.tools else NATIVE_TOOL_DEFS
        
        # [HITL Feedback Loop Injection]
        # 마지막 메시지가 도구 실행 결과(role: tool)이고 실패(success: False)인 경우 
        # LLM에게 자가 수정을 유도하는 가이드를 주입합니다.
        last_msg = current_messages[-1] if current_messages else None
        if last_msg and last_msg.get("role") == "tool":
            try:
                content_obj = json.loads(last_msg.get("content", "{}"))
                if isinstance(content_obj, dict) and not content_obj.get("success", True):
                    error_msg = content_obj.get("error", "Unknown error")
                    logger.warning(f"⚠️ [Agent-{request_id}] 도구 실행 실패 감지 (HITL 피드백 주입 중)")
                    
                    # 피드백 가이드 메시지 생성 (Ollama/vLLM이 이전 도구 결과의 연장선으로 이해하도록 구성)
                    feedback_guidance = f"\n\n[SYSTEM FEEDBACK]\n도구 실행 중 오류가 발생했습니다: {error_msg}\n원인을 분석하고 필요한 경우 수정된 인자로 다시 시도하거나 다른 방법을 찾아주세요."
                    last_msg["content"] = last_msg.get("content", "") + feedback_guidance
                    save_agent_log(request_id, "Feedback Injected", error_msg)
            except Exception as e:
                logger.debug(f"🔍 [Agent-{request_id}] 피드백 주입 시도 실패: {e}")

        # [Single Turn Request]
        # 내부 루프를 제거하고 LLM에게 한 번의 추론(Thinking)을 요청합니다.
        # 도구 호출(Tool Calls)이 발생하면 Void IDE가 이를 캡처하여 사용자에게 승인(Accept)을 요청하게 됩니다.
        logger.info(f"📤 [Agent-{request_id}] [LLM REQ] LLM에게 답변 요청 중...")
        full_ollama_resp = await call_llm(current_messages, tools)
        
        logger.info(f"📥 [Agent-{request_id}] [LLM RESP] 응답 수신 완료")
        
        # 결과 반환 (스트리밍 여부에 따라)
        if request.stream:
            return StreamingResponse(
                generate_pseudo_stream_hitl(full_ollama_resp),
                media_type="text/event-stream"
            )
        else:
            return full_ollama_resp
        
    except Exception as e:
        logger.error(f"❌ [Agent-{request_id}] 처리 중 치명적 에러: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def call_llm(messages: List[Dict], tools: Optional[List] = None):
    """LLM(Ollama, vLLM, OpenAI 등)의 OpenAI 호환 API 호출"""
    async with httpx.AsyncClient(timeout=config["llm"]["timeout"]) as client:
        # OpenAI 호환 엔드포인트
        url = f"{config['llm']['base_url']}/chat/completions"
        headers = {}
        api_key = str(config["llm"].get("api_key", "")).strip()
        # api_key가 존재하고, "not-needed"가 아니며, 빈 문자열이 아닌 경우에만 헤더 추가
        if api_key and api_key.lower() != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": config["llm"]["model"],
            "messages": messages,
            "stream": False,
            "temperature": 0
        }
        if tools:
            payload["tools"] = tools
            
        logger.debug(f"📡 [LLM TX] Payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        
        # OpenAI 규격 응답에서 message 추출하여 Ollama 형식과 비슷하게 반환
        result = resp.json()
        return result

def generate_pseudo_stream_hitl(full_resp: Dict):
    """
    LLM 응답을 OpenAI 호환 SSE 스트림으로 변환하여 전송합니다.
    HITL 모드에서는 tool_calls가 포함될 수 있으므로 이를 고려합니다.
    """
    choice = full_resp.get("choices", [{}])[0]
    msg = choice.get("message", {})
    content = msg.get("content", "")
    tool_calls = msg.get("tool_calls", [])
    
    resp_id = full_resp.get("id", "hitl-" + datetime.now().strftime("%Y%m%d%H%M%S"))
    model_name = full_resp.get("model", config["llm"]["model"])
    created_time = full_resp.get("created", int(datetime.now().timestamp()))

    # 1. Start chunk (role)
    chunk = {
        "id": resp_id, "object": "chat.completion.chunk", "created": created_time, "model": model_name,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # 2. Content chunk (if any)
    if content:
        chunk = {
            "id": resp_id, "object": "chat.completion.chunk", "created": created_time, "model": model_name,
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # 3. Tool Calls chunk (if any)
    if tool_calls:
        chunk = {
            "id": resp_id, "object": "chat.completion.chunk", "created": created_time, "model": model_name,
            "choices": [{"index": 0, "delta": {"tool_calls": tool_calls}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # 4. End chunk
    chunk = {
        "id": resp_id, "object": "chat.completion.chunk", "created": created_time, "model": model_name,
        "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}]
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"

def format_to_openai_response(ollama_resp: Dict):
    """Ollama 응답 형식을 OpenAI 규격으로 변환"""
    choice = ollama_resp.get("choices", [{}])[0]
    message = choice.get("message", {})
    return {
        "id": "agent-" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": ollama_resp.get("model", config["llm"]["model"]),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message.get("content", "")
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config["agent"]["host"], port=config["agent"]["port"])
