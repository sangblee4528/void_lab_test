"""
proxy_server.py - LLM 통신 중계 및 규격 변환 메인 서버

Void IDE와 Ollama 사이에서 메시지를 중계하고,
요청/응답 형식을 변환하며, 모든 통신을 로깅합니다.

실행 방법:
    uvicorn proxy_server:app --host 127.0.0.1 --port 8000 --reload
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
 # 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))
from typing import Dict, Any, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel

# 로컬 모듈 임포트
from proxy_adapter import OllamaAdapter, RequestValidator
from inventory import get_inventory, ToolInventory

# 설정 파일 로드
CONFIG_PATH = Path(__file__).parent / "proxy_config" / "proxy_config.json"

def load_config() -> Dict[str, Any]:
    """설정 파일을 로드합니다."""
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
            
        # 프로파일 지원: active_profile이 있으면 해당 설정을 llm 섹션으로 복사
        if "active_profile" in config and "llm_profiles" in config:
            active = config["active_profile"]
            if active in config["llm_profiles"]:
                config["llm"] = config["llm_profiles"][active]
                
        return config
    except Exception as e:
        print(f"[Config] 설정 파일 로드 실패: {e}, 기본값 사용")
        return {
            "llm": {
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen2.5-coder:7b",
                "api_key": "not-needed",
                "timeout": 60
            },
            "proxy": {
                "host": "127.0.0.1",
                "port": 8000
            },
            "logging": {
                "level": "DEBUG"
            }
        }

config = load_config()

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, config["logging"]["level"]),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("proxy_server.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("proxy_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 초기화 및 종료 시 정리"""
    logger.info("=" * 60)
    logger.info("🚀 Proxy Server 시작")
    logger.info(f"LLM Provider: {config['llm']['provider']}")
    logger.info(f"LLM Base URL: {config['llm']['base_url']}")
    logger.info(f"Default Model: {config['llm']['model']}")
    logger.info(f"Database Path: {config.get('database', {}).get('path', 'Not Configured')}")
    logger.info("=" * 60)
    
    # MCP 서버에서 도구 목록 가져오기
    inventory = get_inventory()
    try:
        tools = await inventory.fetch_tools_from_mcp()
        logger.info(f"📦 인벤토리 로드 완료: {len(tools)}개 도구")
    except Exception as e:
        logger.warning(f"⚠️ MCP 서버 연결 실패, 기본 도구 사용: {e}")
    
    yield
    logger.info("👋 Proxy Server 종료")


# FastAPI 앱 생성
app = FastAPI(
    title="Void Lab Test - Proxy Server",
    description="LLM 통신 중계 및 규격 변환 서버",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 요청/응답 모델
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


class ChatResponse(BaseModel):
    id: str
    object: str
    created: Optional[str] = None
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]


# 어댑터 및 인벤토리 인스턴스
adapter = OllamaAdapter()
validator = RequestValidator()


@app.get("/")
async def root():
    """헬스 체크 엔드포인트"""
    return {
        "status": "running",
        "service": "Void Lab Test Proxy Server",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/v1/models")
async def list_models():
    """사용 가능한 모델 목록 반환"""
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
async def chat_completions(request: ChatRequest, raw_request: Request):
    """
    채팅 완성 엔드포인트 (OpenAI 호환)
    
    🔍 분석 포인트 1: Void가 보낸 툴 명세와 질문 내용 확인
    🔍 분석 포인트 2: LLM 응답에서 도구 호출 여부 확인
    """
    request_id = datetime.now().strftime("%H%M%S%f")
    
    # 요청 로깅
    logger.info("=" * 60)
    logger.info(f"📥 [REQ-{request_id}] 새 요청 수신")
    logger.info(f"   모델: {request.model or config['llm']['model']}")
    logger.info(f"   메시지 수: {len(request.messages)}")
    logger.info(f"   도구 수: {len(request.tools) if request.tools else 0}")
    
    # 메시지 내용 상세 로깅
    for i, msg in enumerate(request.messages):
        role = msg.role
        content = msg.content[:100] if msg.content else "(no content)"
        logger.debug(f"   메시지[{i}] {role}: {content}...")
    
    # 요청 유효성 검증
    is_valid, error = validator.validate_chat_request(request.dict())
    if not is_valid:
        logger.error(f"❌ 요청 유효성 검증 실패: {error}")
        raise HTTPException(status_code=400, detail=error)
    
    # 도구 목록 준비 (요청에 없으면 인벤토리에서 가져오기)
    tools = request.tools
    if not tools:
        inventory = get_inventory()
        tools = inventory.get_tools_for_llm()
        logger.info(f"📦 인벤토리에서 도구 로드: {len(tools)}개")
    
    # LLM 요청 형식으로 변환 (어댑터는 OpenAI 규격을 따름)
    ollama_request = adapter.convert_to_ollama_request(
        messages=[msg.dict(exclude_none=True) for msg in request.messages],
        tools=tools,
        model=request.model or config["llm"]["model"],
        stream=request.stream
    )
    
    logger.info(f"🔄 [REQ-{request_id}] LLM으로 요청 전송 중...")
    logger.debug(f"   URL: {config['llm']['base_url']}/chat/completions")
    logger.debug(f"   요청: {json.dumps(ollama_request, ensure_ascii=False, indent=2)}")
    
    # Ollama API 호출
    try:
        if request.stream:
            async def stream_generator():
                async with httpx.AsyncClient(timeout=config["llm"]["timeout"]) as client:
                    llm_url = f"{config['llm']['base_url']}/chat/completions"
                    headers = {}
                    if config["llm"].get("api_key") and config["llm"]["api_key"] != "not-needed":
                        headers["Authorization"] = f"Bearer {config['llm']['api_key']}"
                        
                    async with client.stream("POST", llm_url, json=ollama_request, headers=headers) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            if line.startswith("data: "):
                                data = line[6:]
                                if data == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data)
                                    converted_chunk = adapter.convert_chunk_from_ollama(chunk)
                                    logger.debug(f"📡 [REQ-{request_id}] 스트리밍 청크 변환 완료")
                                    yield converted_chunk
                                except json.JSONDecodeError:
                                    logger.error(f"❌ [REQ-{request_id}] 청크 파싱 실패: {data}")
                                    continue
                            else:
                                logger.info(f"ℹ️ [REQ-{request_id}] 비-데이터 라인(Full JSON) 수신")
                                try:
                                    # Ollama가 stream: false로 응답하여 JSON 한 줄이 왔을 경우 처리
                                    full_resp_raw = json.loads(line)
                                    # 1. Ollama -> OpenAI Full Response 변환 (도구 추출 포함)
                                    openai_full = adapter.convert_from_ollama_response(full_resp_raw)
                                    # 2. OpenAI Full Response -> OpenAI Chunks 변환 (리스트 반환)
                                    converted_chunks = adapter.convert_to_chunk_from_full_response(openai_full)
                                    logger.info(f"📡 [REQ-{request_id}] 비-데이터 응답을 {len(converted_chunks)}개의 청크로 로 분할하여 전송합니다.")
                                    for idx, chunk in enumerate(converted_chunks):
                                        logger.debug(f"   청크[{idx}]: {chunk}")
                                        yield chunk
                                except Exception as e:
                                    logger.error(f"❌ [REQ-{request_id}] 비-데이터 라인 처리 중 에러: {e}")
                                    continue
                
                logger.debug(f"🏁 [REQ-{request_id}] 스트림 종료 신호 전송")
                yield "data: [DONE]\n\n"

            logger.info(f"📡 [REQ-{request_id}] 스트리밍 응답 시작")
            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        else:
            async with httpx.AsyncClient(timeout=config["llm"]["timeout"]) as client:
                llm_url = f"{config['llm']['base_url']}/chat/completions"
                headers = {}
                if config["llm"].get("api_key") and config["llm"]["api_key"] != "not-needed":
                    headers["Authorization"] = f"Bearer {config['llm']['api_key']}"
                    
                response = await client.post(llm_url, json=ollama_request, headers=headers)
                response.raise_for_status()
                
                ollama_response = response.json()
            
            # 응답 변환
            openai_response = adapter.convert_from_ollama_response(ollama_response)
            
            # 응답 로깅
            logger.info(f"📤 [REQ-{request_id}] 응답 반환")
            
            # 도구 호출 여부 확인 (분석 포인트 2)
            tool_calls = adapter.extract_tool_calls(openai_response)
            if tool_calls:
                logger.info(f"🔧 [REQ-{request_id}] LLM이 도구 호출 요청!")
                for tc in tool_calls:
                    func = tc.get("function", {})
                    logger.info(f"   → {func.get('name')}: {func.get('arguments')}")
            else:
                content = openai_response["choices"][0]["message"].get("content", "")
                logger.info(f"💬 [REQ-{request_id}] 일반 응답: {content[:100]}...")
            
            logger.info("=" * 60)
            return openai_response

    except httpx.ReadTimeout:
        logger.error(f"⏱️ [REQ-{request_id}] LLM 응답 시간 초과 (ReadTimeout)")
        if request.stream:
            async def error_generator():
                yield f"data: {json.dumps({'error': 'LLM 응답 시간이 초과되었습니다. 모델 로딩 중이거나 서버 부하가 높을 수 있습니다.'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(error_generator(), media_type="text/event-stream")
        else:
            raise HTTPException(status_code=504, detail="LLM 응답 시간 초과 (ReadTimeout)")
            
    except httpx.ConnectTimeout:
        logger.error(f"⏱️ [REQ-{request_id}] LLM 연결 시간 초과 (ConnectTimeout)")
        raise HTTPException(status_code=504, detail="LLM 연결 시간 초과")
        
    except httpx.TimeoutException:
        logger.error(f"⏱️ [REQ-{request_id}] LLM 기타 타임아웃 발생")
        raise HTTPException(status_code=504, detail="LLM 요청 시간 초과")
        
    except httpx.HTTPError as e:
        logger.error(f"❌ [REQ-{request_id}] LLM 연결 실패: {e}")
        raise HTTPException(status_code=502, detail=f"LLM 연결 실패: {str(e)}")


@app.get("/tools")
async def get_tools():
    """등록된 도구 목록 조회"""
    inventory = get_inventory()
    return {
        "tools": inventory.get_tools_for_llm()
    }


@app.post("/tools/refresh")
async def refresh_tools():
    """MCP 서버에서 도구 목록 새로고침"""
    inventory = get_inventory()
    try:
        tools = await inventory.fetch_tools_from_mcp()
        return {
            "status": "success",
            "tools_count": len(tools)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "proxy_server:app",
        host=config["proxy"]["host"],
        port=config["proxy"]["port"],
        reload=True,
        log_level="debug"
    )
