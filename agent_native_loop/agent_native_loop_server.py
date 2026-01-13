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
logger = logging.getLogger("agent_native")
# mcp_client 로거도 같은 핸들러를 사용하도록 설정 (상속)
logging.getLogger("mcp_client").setLevel(getattr(logging, config["logging"]["level"]))

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
        
        # 도구 목록 로드 (로컬 native_tools 사용)
        tools = request.tools
        if not tools:
            logger.info(f"🔍 [Agent-{request_id}] 로컬 네이티브 도구 목록 사용 중...")
            tools = NATIVE_TOOL_DEFS
            logger.info(f"📦 [Agent-{request_id}] {len(tools)}개의 네이티브 도구 발견")
        
        # --------------------------------------------------------
        # 🔄 Autonomous Agent Loop (n8n 스타일의 상태 머신)
        # --------------------------------------------------------
        # 이 루프는 n8n AI Agent 노드의 'Looping & State Machine' 아키텍처를 구현합니다.
        # 단순히 결과를 기다리는 것이 아니라, 스스로 다음 행동을 결정하고 실행하는 능동적 구조입니다.
        max_iterations = 5
        for i in range(max_iterations):
            logger.info(f"🔄 [Agent-{request_id}] 반복 {i+1}단계 실행 중...")
            
            # [상태 1: Thinking] LLM에게 현재까지의 대화 이력을 전달하여 '생각'을 요청합니다.
            # n8n의 "AI Agent Node"가 LLM 모델에 질문을 던지는 과정과 동일합니다.
            logger.info(f"📤 [Agent-{request_id}] [LLM REQ] LLM에게 답변 요청 중...")
            full_ollama_resp = await call_llm(current_messages, tools)
            
            logger.info(f"📥 [Agent-{request_id}] [LLM RESP] 응답 수신 완료")
            logger.debug(f"--- [LLM RESP Detail] ---\n{json.dumps(full_ollama_resp, ensure_ascii=False, indent=2)}\n-------------------------")

            choice = full_ollama_resp.get("choices", [{}])[0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls", [])
            content = message.get("content", "")
            
            # [상태 2: Fallback/Analysis] 모델의 응답이 규격화된 tool_calls인지, 혹은 텍스트 내 JSON인지 분석합니다.
            # n8n이 LLM 응답을 파싱하여 다음 노드(도구)를 실행할지 결정하는 "Output Parser" 단계입니다.
            if not tool_calls and content:
                # 마크다운 코드 블록 제거 및 JSON 추출 시도
                json_str = content.strip()
                if "```json" in json_str:
                    match = re.search(r"```json\s*(\{.*?\})\s*```", json_str, re.DOTALL)
                    json_str = match.group(1) if match else json_str
                elif "```" in json_str:
                    match = re.search(r"```\s*(\{.*?\})\s*```", json_str, re.DOTALL)
                    json_str = match.group(1) if match else json_str
                
                # 중괄호 범위를 찾아 JSON만 추출 (가장 바깥쪽 { })
                if "{" in json_str and "}" in json_str:
                    start_idx = json_str.find("{")
                    # 단순 find/rfind는 중첩된 중괄호에서 위험할 수 있지만, 
                    # 여기서는 가장 바깥쪽 패턴을 찾기 위해 시도
                    # 더 정교하게는 괄호 매칭을 해야 함
                    temp_str = json_str[start_idx:]
                    depth = 0
                    end_idx = -1
                    for idx, char in enumerate(temp_str):
                        if char == '{': depth += 1
                        elif char == '}':
                            depth -= 1
                            if depth == 0:
                                end_idx = idx
                                break
                    if end_idx != -1:
                        json_str = temp_str[:end_idx+1]

                try:
                    potential_tool = json.loads(json_str)
                    if "name" in potential_tool and "arguments" in potential_tool:
                        tool_calls = [{
                            "id": f"call_{i}_{datetime.now().strftime('%M%S')}",
                            "type": "function",
                            "function": {
                                "name": potential_tool["name"],
                                "arguments": json.dumps(potential_tool["arguments"]) if isinstance(potential_tool["arguments"], dict) else potential_tool["arguments"]
                            }
                        }]
                        message["tool_calls"] = tool_calls
                        logger.info(f"💡 [Agent-{request_id}] Content에서 JSON 도구 호출 추출 완료!")
                except Exception as e:
                    logger.debug(f"🔍 [Agent-{request_id}] JSON 추출 시도 실패: {e}")

            # 도구 호출이 있으면 content를 비워줌 (모델에 따라 중복으로 인식할 수 있음)
            if tool_calls:
                message["content"] = ""

            # [상태 3: Exit Condition] 도구 호출이 없으면 에이전트가 "할 일을 다 했다"고 판단하여 최종 답변 상태가 됩니다.
            # n8n 워크플로우가 최종 'Response' 출력을 내보내는 지점입니다.
            if not tool_calls:
                logger.info(f"✅ [Agent-{request_id}] 최종 응답 도달")
                final_resp = format_to_openai_response(full_ollama_resp)
                
                if request.stream:
                    logger.info(f"📡 [Agent-{request_id}] 스트리밍 형식으로 변환하여 반환")
                    return StreamingResponse(
                        generate_pseudo_stream(final_resp),
                        media_type="text/event-stream"
                    )
                else:
                    return final_resp
            
            # [상태 4: Action/Execution] 모델이 요청한 도구들을 실제로 실행합니다.
            # 이 부분이 Void IDE와 가장 큰 차별점으로, 사용자의 클릭 없이 서버가 '자동 실행'을 수행하는 n8n의 Executor 역할입니다.
            logger.info(f"🔧 [Agent-{request_id}] LLM이 {len(tool_calls)}개의 도구 호출 요청")
            current_messages.append(message) # LLM의 도구 요청 메시지 추가 (History Update)
            
            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"])
                call_id = tool_call.get("id")
                
                logger.info(f"🛠️  [Agent-{request_id}] [NATIVE TOOL CALL] {func_name} 시작")
                logger.info(f"   → 인자(Args): {args} [ID: {call_id}]")
                save_agent_log(request_id, f"Native Tool Call: {func_name}", json.dumps(args))
                
                # 로컬 네이티브 도구 직접 실행 (MCP 서버 호출 없음)
                if func_name in NATIVE_TOOL_REGISTRY:
                    try:
                        # 동기 함수인 경우를 대비해 처리 (현재는 모두 동기)
                        result = NATIVE_TOOL_REGISTRY[func_name](**args)
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
                else:
                    result = {"success": False, "error": f"정의되지 않은 도구: {func_name}"}
                
                logger.info(f"✅ [Agent-{request_id}] [NATIVE TOOL RESULT] {func_name} 완료")
                logger.debug(f"   → 결과: {json.dumps(result, ensure_ascii=False)}")
                
                # [상태 5: Feedback/State Update] 도구 실행 결과(Observation)를 대화 이력에 추가합니다.
                # role: "tool"을 통해 모델에게 "이것은 네가 시킨 행동의 결과야"라고 알려줍니다.
                # 이를 통해 다음 루프(상태 1)에서 모델은 이 결과를 바탕으로 다음 행동을 결정하게 됩니다.
                
                # Feedback Loop: 결과가 실패인 경우, 모델에게 명시적으로 수정을 요청하는 프롬프트 추가 가능
                if not result.get("success", True):
                    error_msg = result.get("error", "Unknown error")
                    logger.warning(f"⚠️  [Agent-{request_id}] 도구 실행 실패 감지: {func_name}")
                    
                    feedback_content = f"도구 실행 중 오류가 발생했습니다: {error_msg}\n원인을 분석하고 필요한 경우 수정된 인자로 다시 시도하거나 다른 방법을 찾아주세요."
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps({"status": "error", "message": feedback_content, "raw_result": result}, ensure_ascii=False)
                    })
                else:
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False)
                    })
                
            # [Loop Back] 루프의 처음(상태 1)으로 돌아가 정보를 주입받은 LLM의 다음 판단을 기다립니다.
        
        raise HTTPException(status_code=500, detail="최대 반복 횟수 초과")
        
    except Exception as e:
        logger.error(f"❌ [Agent-{request_id}] 처리 중 치명적 에러: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def call_llm(messages: List[Dict], tools: Optional[List] = None):
    """LLM(Ollama, vLLM, OpenAI 등)의 OpenAI 호환 API 호출"""
    async with httpx.AsyncClient(timeout=config["llm"]["timeout"]) as client:
        # OpenAI 호환 엔드포인트
        url = f"{config['llm']['base_url']}/chat/completions"
        headers = {}
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

def generate_pseudo_stream(final_resp: Dict):
    """일반 응답을 SSE 스트림 형식으로 변환"""
    # 첫 번째 청크: role만 전송
    chunk1 = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None
            }
        ]
    }
    yield f"data: {json.dumps(chunk1, ensure_ascii=False)}\n\n"
    
    # 두 번째 청크: content 전송
    chunk2 = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {"content": final_resp["choices"][0]["message"]["content"]},
                "finish_reason": None
            }
        ]
    }
    yield f"data: {json.dumps(chunk2, ensure_ascii=False)}\n\n"
    
    # 세 번째 청크: finish_reason
    chunk3 = {
        "id": final_resp["id"],
        "object": "chat.completion.chunk",
        "created": final_resp["created"],
        "model": final_resp["model"],
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }
        ]
    }
    yield f"data: {json.dumps(chunk3, ensure_ascii=False)}\n\n"
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
