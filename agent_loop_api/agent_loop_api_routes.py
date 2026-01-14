"""
agent_loop_api_routes.py - API 라우트 정의

모든 REST API 엔드포인트를 정의합니다.
승인 대기, 승인/거절, 결과 조회 등의 로직을 포함합니다.
"""

import json
import re
import sqlite3
import httpx
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent_loop_api_models import (
    ChatRequest, ChatMessage, ChatCompletionResponse,
    PendingApproval, ApprovalResponse, ApprovalStatus, ToolCallInfo
)
from agent_loop_api_tools import TOOL_DEFS, TOOL_REGISTRY, DB_PATH

# 설정 로드
CONFIG_PATH = (Path(__file__).parent / "agent_loop_config" / "agent_loop_config.json").resolve()

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# 라우터 생성
router = APIRouter()

# 메모리 내 대기 요청 저장소 (DB와 동기화)
pending_requests: Dict[str, Dict[str, Any]] = {}


# ============================================================
# 헬퍼 함수
# ============================================================

def generate_request_id() -> str:
    """고유 요청 ID 생성"""
    return f"req_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


async def call_llm(messages: List[Dict], tools: Optional[List] = None) -> Dict:
    """LLM 호출"""
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
        
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def save_pending_to_db(request_id: str, tool_calls: List, messages: List, status: str = "pending"):
    """대기 요청을 DB에 저장"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT OR REPLACE INTO pending_requests 
           (request_id, tool_calls, messages, status, updated_at) 
           VALUES (?, ?, ?, ?, ?)""",
        (request_id, json.dumps(tool_calls), json.dumps(messages), status, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def update_pending_status(request_id: str, status: str, result: str = None):
    """대기 요청 상태 업데이트"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE pending_requests SET status = ?, result = ?, updated_at = ? WHERE request_id = ?""",
        (status, result, datetime.now().isoformat(), request_id)
    )
    conn.commit()
    conn.close()


def get_pending_from_db(request_id: str) -> Optional[Dict]:
    """DB에서 대기 요청 조회"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT request_id, tool_calls, messages, status, result FROM pending_requests WHERE request_id = ?",
        (request_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "request_id": row[0],
            "tool_calls": json.loads(row[1]),
            "messages": json.loads(row[2]),
            "status": row[3],
            "result": json.loads(row[4]) if row[4] else None
        }
    return None


def detect_tool_calls(assistant_msg: Dict) -> List[Dict]:
    """LLM 응답에서 도구 호출 감지"""
    detected = assistant_msg.get("tool_calls", [])
    if not isinstance(detected, list):
        detected = []
    
    # content에서 JSON 형태의 도구 호출 추가 감지
    content = assistant_msg.get("content", "")
    if content:
        try:
            json_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if not json_matches:
                start_idx = content.find("{")
                end_idx = content.rfind("}")
                if start_idx != -1 and end_idx > start_idx:
                    json_matches = [content[start_idx:end_idx+1]]
            
            for match in json_matches:
                try:
                    potential = json.loads(match)
                    if isinstance(potential, dict) and "name" in potential and ("arguments" in potential or "args" in potential):
                        if not any(tc.get("function", {}).get("name") == potential["name"] for tc in detected):
                            
                            args_payload = potential.get("arguments") or potential.get("args") or {}
                            if isinstance(args_payload, dict):
                                args_payload = json.dumps(args_payload, ensure_ascii=False)
                            
                            detected.append({
                                "id": f"call_{datetime.now().strftime('%H%M%S%f')}",
                                "type": "function",
                                "function": {
                                    "name": potential["name"],
                                    "arguments": args_payload
                                }
                            })
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
    
    return detected


# ============================================================
# API 엔드포인트
# ============================================================

@router.get("/")
async def root():
    """서버 상태 확인"""
    return {
        "status": "online",
        "agent": config["agent"]["name"],
        "version": "1.0.0",
        "endpoints": {
            "chat": "POST /v1/chat/completions",
            "pending": "GET /v1/pending",
            "approve": "POST /v1/approve/{request_id}",
            "reject": "POST /v1/reject/{request_id}",
            "result": "GET /v1/result/{request_id}"
        }
    }


@router.get("/v1/models")
async def list_models():
    """모델 목록"""
    return {
        "object": "list",
        "data": [{
            "id": config["llm"]["model"],
            "object": "model",
            "created": int(datetime.now().timestamp()),
            "owned_by": config["llm"]["provider"]
        }]
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    채팅 요청 처리
    - 도구 호출이 감지되면 'pending' 상태로 응답
    - 클라이언트가 /v1/approve 또는 /v1/reject 호출 필요
    """
    request_id = generate_request_id()
    messages = [msg.model_dump(exclude_none=True) for msg in request.messages]
    tools = request.tools if request.tools else TOOL_DEFS
    
    # LLM 호출
    llm_response = await call_llm(messages, tools)
    choice = llm_response.get("choices", [{}])[0]
    assistant_msg = choice.get("message", {})
    
    # 도구 호출 감지
    tool_calls = detect_tool_calls(assistant_msg)
    
    if not tool_calls:
        # 도구 호출 없음 - 바로 응답 반환
        return llm_response
    
    # 도구 호출 있음 - pending 상태로 저장
    # 감지된 도구 호출을 assistant_msg에 반영 (text로 온 경우를 대비)
    if tool_calls and not assistant_msg.get("tool_calls"):
        assistant_msg["tool_calls"] = tool_calls
        assistant_msg["content"] = None
    
    messages.append(assistant_msg)
    
    tool_call_infos = [
        ToolCallInfo(
            id=tc.get("id", ""),
            name=tc["function"]["name"],
            arguments=tc["function"]["arguments"] if isinstance(tc["function"]["arguments"], dict) 
                      else json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) 
                      else {}
        )
        for tc in tool_calls
    ]
    
    pending = PendingApproval(
        request_id=request_id,
        status=ApprovalStatus.PENDING,
        tool_calls=tool_call_infos,
        created_at=datetime.now(),
        message=f"다음 도구 실행에 대한 승인이 필요합니다: {', '.join(tc.name for tc in tool_call_infos)}"
    )
    
    # 메모리 및 DB에 저장
    pending_requests[request_id] = {
        "tool_calls": tool_calls,
        "messages": messages,
        "status": "pending"
    }
    save_pending_to_db(request_id, tool_calls, messages)
    
    # 승인 대기 응답 반환
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": config["llm"]["model"],
        "choices": [{
            "index": 0,
            "message": assistant_msg,
            "finish_reason": "tool_calls"
        }],
        "approval_required": True,
        "pending_approval": pending.model_dump()
    }


@router.get("/v1/pending")
async def list_pending():
    """대기 중인 승인 요청 목록"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT request_id, tool_calls, status, created_at FROM pending_requests WHERE status = 'pending'"
    )
    rows = cursor.fetchall()
    conn.close()
    
    pending_list = []
    for row in rows:
        tool_calls = json.loads(row[1])
        pending_list.append({
            "request_id": row[0],
            "tools": [tc["function"]["name"] for tc in tool_calls],
            "status": row[2],
            "created_at": row[3]
        })
    
    return {"pending": pending_list, "count": len(pending_list)}


@router.post("/v1/approve/{request_id}")
async def approve_request(request_id: str):
    """도구 실행 승인"""
    # DB에서 조회
    pending = get_pending_from_db(request_id)
    if not pending:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
    
    if pending["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {pending['status']}")
    
    # 도구 실행
    tool_calls = pending["tool_calls"]
    messages = pending["messages"]
    
    for tc in tool_calls:
        func_name = tc["function"]["name"]
        args = tc["function"]["arguments"]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except:
                args = {}
        
        if func_name in TOOL_REGISTRY:
            try:
                result = TOOL_REGISTRY[func_name](**args) if isinstance(args, dict) else TOOL_REGISTRY[func_name]()
            except Exception as e:
                result = {"success": False, "error": str(e)}
        else:
            result = {"success": False, "error": f"Tool '{func_name}' not found"}
        
        messages.append({
            "role": "tool",
            "tool_call_id": tc.get("id", "none"),
            "name": func_name,
            "content": json.dumps(result, ensure_ascii=False)
        })
    
    # LLM 최종 응답 요청
    final_response = await call_llm(messages, TOOL_DEFS)
    
    # 상태 업데이트
    update_pending_status(request_id, "completed", json.dumps(final_response, ensure_ascii=False))
    
    if request_id in pending_requests:
        del pending_requests[request_id]
    
    return {
        "request_id": request_id,
        "status": "approved",
        "message": "도구가 실행되었습니다.",
        "response": final_response
    }


@router.post("/v1/reject/{request_id}")
async def reject_request(request_id: str):
    """도구 실행 거절"""
    pending = get_pending_from_db(request_id)
    if not pending:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
    
    if pending["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {pending['status']}")
    
    # 상태 업데이트
    update_pending_status(request_id, "rejected", json.dumps({"message": "사용자가 거절함"}))
    
    if request_id in pending_requests:
        del pending_requests[request_id]
    
    return ApprovalResponse(
        request_id=request_id,
        status=ApprovalStatus.REJECTED,
        message="도구 실행이 거절되었습니다."
    )


@router.get("/v1/result/{request_id}")
async def get_result(request_id: str):
    """결과 조회"""
    pending = get_pending_from_db(request_id)
    if not pending:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
    
    return {
        "request_id": request_id,
        "status": pending["status"],
        "result": pending["result"]
    }
