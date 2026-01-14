"""
# agent_native_loop_server.py - 자율적으로 도구를 실행하는 능동적 대리인 서버 (Native 버전)

LLM이 도구 호출을 요청하면, 클라이언트(Void)에게 반환하기 전에 
직접 MCP 서버와 통신하여 도구를 실행하고 결과를 LLM에게 다시 전달합니다.
최종 답변이 나올 때까지 이 과정을 반복합니다.
"""

import asyncio
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

async def ask_terminal_approval(func_name: str, args: Dict) -> bool:
    """
    터미널에서 도구 실행 승인을 요청합니다.
    y/Y/yes/Yes 입력 시 True, 그 외는 False 반환
    """
    print("\n" + "="*60)
    print(f"🔧 도구 실행 승인 요청")
    print(f"   도구: {func_name}")
    print(f"   인자: {json.dumps(args, ensure_ascii=False, indent=2)}")
    print("="*60)
    
    # async 방식으로 input() 호출 (이벤트 루프 블로킹 방지)
    loop = asyncio.get_event_loop()
    user_input = await loop.run_in_executor(None, lambda: input("실행하시겠습니까? (y/n): "))
    
    approved = user_input.strip().lower() in ['y', 'yes', '예', 'ㅛ']
    if approved:
        print("✅ 승인됨 - 도구를 실행합니다.\n")
    else:
        print("❌ 거절됨 - 도구 실행을 건너뜁니다.\n")
    
    return approved

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 초기화"""
    logger.info("Agent Native Loop Server starting (Truly Native Mode)...")
    logger.info(f"{len(NATIVE_TOOL_DEFS)} native tools loaded")
    yield
    logger.info("Agent Native Loop Server stopped")

app = FastAPI(title="Void Lab Test - Active Agent Native Loop", lifespan=lifespan)
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

@app.get("/")
async def root():
    """서버 상태 및 LLM 연결 확인용 루트 엔드포인트"""
    llm_connected = False
    llm_info = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{config['llm']['base_url']}/models")
            llm_connected = resp.status_code == 200
            llm_info = resp.json() if llm_connected else {"error": resp.text}
    except Exception as e:
        llm_info = {"error": str(e)}

    return {
        "status": "online",
        "agent": "Agent Native Loop Server",
        "version": "1.1.0",
        "llm_connection": {
            "status": "connected" if llm_connected else "disconnected",
            "base_url": config['llm']['base_url'],
            "model": config['llm']['model'],
            "details": llm_info
        },
        "endpoints": {
            "models": "/v1/models",
            "chat": "/v1/chat/completions (POST only)"
        }
    }

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

@app.get("/v1/chat/completions")
async def chat_completions_get():
    """GET 요청 시 안내 메시지 반환"""
    return {
        "error": "Method Not Allowed",
        "message": "이 엔드포인트는 POST 요청만 지원합니다. Void IDE나 API 클라이언트 설정에서 POST 메서드를 사용하고 있는지 확인해주세요.",
        "hint": "OpenAI 호환 API 규격은 채팅 완료를 위해 POST /v1/chat/completions를 사용합니다."
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    자율 실행 루프를 포함한 채팅 엔드포인트
    """
    request_id = datetime.now().strftime("%H%M%S")
    logger.info(f"[Agent-{request_id}] New request received: {request.messages[-1].content}")
    save_agent_log(request_id, "Request Received", request.messages[-1].content)
    
    try:
        current_messages = [msg.model_dump(exclude_none=True) for msg in request.messages]
        tools = request.tools if request.tools else NATIVE_TOOL_DEFS
        
        max_iterations = 5
        iteration = 0
        final_response = None
        
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"[Agent-{request_id}] [LLM REQ] Loop {iteration}/{max_iterations}")
            
            # [HITL Feedback Loop Injection]
            last_msg = current_messages[-1] if current_messages else None
            if last_msg and last_msg.get("role") == "tool":
                try:
                    content_obj = json.loads(last_msg.get("content", "{}"))
                    if isinstance(content_obj, dict) and not content_obj.get("success", True):
                        error_msg = content_obj.get("error", "Unknown error")
                        feedback_guidance = f"\n\n[SYSTEM FEEDBACK]\n도구 실행 중 오류가 발생했습니다: {error_msg}\n원인을 분석하고 필요한 경우 수정된 인자로 다시 시도하거나 다른 방법을 찾아주세요."
                        last_msg["content"] = last_msg.get("content", "") + feedback_guidance
                except Exception:
                    pass

            # LLM 호출
            full_ollama_resp = await call_llm(current_messages, tools)
            choice = full_ollama_resp.get("choices", [{}])[0]
            assistant_msg = choice.get("message", {})
            current_messages.append(assistant_msg)
            
            # [Tool Call Detection]
            detected_tool_calls = assistant_msg.get("tool_calls", [])
            logger.debug(f"[Agent-{request_id}] Initial tool_calls: {detected_tool_calls}")
            if not isinstance(detected_tool_calls, list):
                detected_tool_calls = []
                
            # content에서 추가로 찾기
            if assistant_msg.get("content"):
                content = assistant_msg["content"].strip()
                logger.debug(f"[Agent-{request_id}] Checking content for tools: {content[:100]}...")
                try:
                    # 1. ```json ... ``` 블록 찾기
                    json_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
                    
                    # 2. 블록이 없으면 텍스트 전체에서 { } 쌍 찾기 (더 견고한 방식)
                    if not json_matches:
                        start_idx = content.find("{")
                        end_idx = content.rfind("}")
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            # 가장 바깥쪽의 { } 블록 하나를 추출
                            json_matches = [content[start_idx:end_idx+1]]
                        else:
                            json_matches = []
                    
                    logger.debug(f"[Agent-{request_id}] Found {len(json_matches)} potential JSON blocks")
                    for match in json_matches:
                        try:
                            potential_tool = json.loads(match)
                            logger.debug(f"[Agent-{request_id}] Parsed JSON: {list(potential_tool.keys())}")
                            # name과 arguments(또는 args)가 있으면 도구 호출로 간주
                            if isinstance(potential_tool, dict) and "name" in potential_tool and ("arguments" in potential_tool or "args" in potential_tool):
                                # 이미 발견된 tool_calls에 동일한 name이 있는지 확인 (중복 방지)
                                if not any(tc.get("function", {}).get("name") == potential_tool["name"] for tc in detected_tool_calls):
                                    logger.info(f"[Agent-{request_id}] Tool call '{potential_tool['name']}' detected in content")
                                    detected_tool_calls.append({
                                        "id": f"call_{datetime.now().strftime('%H%M%S%f')}",
                                        "type": "function",
                                        "function": {
                                            "name": potential_tool["name"],
                                            "arguments": potential_tool.get("arguments") or potential_tool.get("args") or {}
                                        }
                                    })
                        except json.JSONDecodeError as je:
                            logger.debug(f"[Agent-{request_id}] JSONDecodeError for block: {je}")
                            continue
                except Exception as e:
                    logger.debug(f"[Agent-{request_id}] Content parsing error: {e}")

            if not detected_tool_calls:
                logger.info(f"[Agent-{request_id}] Final response received (Loop finished)")
                final_response = full_ollama_resp
                break
            
            # tool_calls 업데이트 (루프 진행을 위해)
            assistant_msg["tool_calls"] = detected_tool_calls
            tool_calls = detected_tool_calls
            
            # 도구 실행 (승인 필요)
            logger.info(f"[Agent-{request_id}] Starting {len(tool_calls)} tools (approval required)")
            rejected = False
            
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        pass
                
                logger.info(f"[Agent-{request_id}] Tool call: {func_name}({args})")
                
                # 🔒 터미널 승인 요청
                approved = await ask_terminal_approval(func_name, args if isinstance(args, dict) else {})
                
                if not approved:
                    rejected = True
                    result = {"success": False, "error": "사용자가 도구 실행을 거절했습니다."}
                    save_agent_log(request_id, f"Tool Rejected: {func_name}", "User rejected")
                elif func_name in NATIVE_TOOL_REGISTRY:
                    try:
                        if isinstance(args, dict):
                            result = NATIVE_TOOL_REGISTRY[func_name](**args)
                        else:
                            result = NATIVE_TOOL_REGISTRY[func_name]()
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
                else:
                    result = {"success": False, "error": f"Tool '{func_name}' not found"}
                
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.get("id", "none"),
                    "name": func_name,
                    "content": json.dumps(result, ensure_ascii=False)
                }
                current_messages.append(tool_msg)
                save_agent_log(request_id, f"Tool Executed: {func_name}", json.dumps(result, ensure_ascii=False))
                
                # 거절 시 루프 중단
                if rejected:
                    logger.info(f"[Agent-{request_id}] User rejected tool execution. Stopping loop.")
                    break
            
            # 거절 시 전체 루프 종료
            if rejected:
                final_response = {
                    "id": "agent-" + datetime.now().strftime("%Y%m%d%H%M%S"),
                    "object": "chat.completion",
                    "created": int(datetime.now().timestamp()),
                    "model": config["llm"]["model"],
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": "사용자가 도구 실행을 거절하여 작업을 중단했습니다."},
                        "finish_reason": "stop"
                    }]
                }
                break

        if not final_response:
            # 최대 횟수 초과 시 마지막 응답 반환
            final_response = full_ollama_resp

        # 결과 반환 (스트리밍 여부에 따라)
        if request.stream:
            return StreamingResponse(
                generate_pseudo_stream_hitl(final_response),
                media_type="text/event-stream"
            )
        else:
            return final_response
        
    except Exception as e:
        logger.error(f"❌ [Agent-{request_id}] 처리 중 치명적 에러: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def call_llm(messages: List[Dict], tools: Optional[List] = None):
    """LLM(Ollama, vLLM, OpenAI 등)의 OpenAI 호환 API 호출"""
    async with httpx.AsyncClient(timeout=config["llm"]["timeout"]) as client:
        url = f"{config['llm']['base_url']}/chat/completions"
        headers = {"Content-Type": "application/json"}
        api_key = str(config["llm"].get("api_key", "")).strip()
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
        
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.RemoteProtocolError as e:
            logger.error(f"❌ LLM 서버(Ollama)가 연결을 강제로 끊었습니다: {e}")
            raise HTTPException(status_code=500, detail=f"LLM Connection Reset: {str(e)}")
        except Exception as e:
            logger.error(f"❌ LLM 호출 중 에러 발생: {e}")
            raise

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
    import signal
    import sys
    
    def signal_handler(sig, frame):
        """Ctrl+C 등 종료 시그널 처리"""
        print("\n🛑 종료 신호 수신. 서버를 정상 종료합니다...")
        sys.exit(0)
    
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # uvicorn 실행 (graceful shutdown 설정 포함)
    config_uvicorn = uvicorn.Config(
        app,
        host=config["agent"]["host"],
        port=config["agent"]["port"],
        loop="asyncio",
        timeout_graceful_shutdown=5  # 5초 내 graceful shutdown
    )
    server = uvicorn.Server(config_uvicorn)
    
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n🛑 키보드 인터럽트. 서버를 종료합니다...")
    finally:
        print("✅ 서버가 정상 종료되었습니다. 포트가 해제되었습니다.")

