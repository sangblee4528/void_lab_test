"""
agent_loop_api_models.py - Pydantic 모델 정의

채팅 요청, 승인 요청, 응답 등의 데이터 모델을 정의합니다.
"""

from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum


class ApprovalStatus(str, Enum):
    """승인 상태"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ChatMessage(BaseModel):
    """채팅 메시지"""
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatRequest(BaseModel):
    """채팅 요청"""
    model: Optional[str] = None
    messages: List[ChatMessage]
    tools: Optional[List[Dict[str, Any]]] = None
    stream: bool = False


class ToolCallInfo(BaseModel):
    """도구 호출 정보"""
    id: str
    name: str
    arguments: Dict[str, Any]


class PendingApproval(BaseModel):
    """대기 중인 승인 요청"""
    request_id: str
    status: ApprovalStatus
    tool_calls: List[ToolCallInfo]
    created_at: datetime
    message: str = "도구 실행 승인이 필요합니다."


class ApprovalResponse(BaseModel):
    """승인/거절 응답"""
    request_id: str
    status: ApprovalStatus
    message: str


class ChatCompletionResponse(BaseModel):
    """채팅 완료 응답"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Optional[Dict[str, int]] = None
    # 승인 대기 시 추가 필드
    approval_required: bool = False
    pending_approval: Optional[PendingApproval] = None
