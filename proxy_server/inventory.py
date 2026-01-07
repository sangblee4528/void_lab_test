"""
inventory.py - LLM에 주입할 툴 인벤토리 관리

MCP 서버에서 사용 가능한 도구 목록을 관리하고,
LLM에게 전달할 도구 명세(메타데이터)를 생성합니다.
"""

import json
import httpx
from typing import List, Dict, Any
import sys
from pathlib import Path

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))

# MCP 서버 기본 설정
MCP_HOST = "http://127.0.0.1:3000"


class ToolInventory:
    """LLM에 주입할 툴 인벤토리 관리 클래스"""
    
    def __init__(self, mcp_host: str = MCP_HOST):
        self.mcp_host = mcp_host
        self._tools: List[Dict[str, Any]] = []
    
    async def fetch_tools_from_mcp(self) -> List[Dict[str, Any]]:
        """
        MCP 서버에서 사용 가능한 도구 목록을 가져옵니다.
        
        Returns:
            List[Dict]: 도구 목록 (MCP 표준 형식)
        """
        async with httpx.AsyncClient() as client:
            try:
                # MCP 서버의 도구 목록 엔드포인트 사용 (GET)
                response = await client.get(
                    f"{self.mcp_host}/tools",
                    timeout=10.0
                )
                response.raise_for_status()
                result = response.json()
                
                if "tools" in result:
                    mcp_tools = result["tools"]
                    # MCP 형식을 OpenAI 형식으로 변환 (LLM용)
                    self._tools = self._convert_mcp_to_openai(mcp_tools)
                    return self._tools
                    
            except httpx.HTTPError as e:
                print(f"[Inventory] MCP 서버 연결 실패: {e}")
                # 기본 도구 목록 반환
                return self._get_default_tools()
        
        return []
    
    def _convert_mcp_to_openai(self, mcp_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        MCP 표준 도구 형식을 OpenAI 함수 호출 형식으로 변환합니다.
        
        MCP 형식: {name, description, inputSchema}
        OpenAI 형식: {type: "function", function: {name, description, parameters}}
        """
        openai_tools = []
        for tool in mcp_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "parameters": tool.get("inputSchema", {})
                }
            })
        return openai_tools
    
    def _get_default_tools(self) -> List[Dict[str, Any]]:
        """
        기본 도구 목록을 반환합니다.
        MCP 서버에 연결할 수 없을 때 사용됩니다.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_docs",
                    "description": "회사 문서에서 정보를 검색합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "검색할 키워드 또는 질문"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_employee_info",
                    "description": "직원 정보를 조회합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "employee_id": {
                                "type": "string",
                                "description": "직원 ID"
                            }
                        },
                        "required": ["employee_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_all_employees",
                    "description": "모든 직원의 목록을 조회합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate_vacation_days",
                    "description": "직원의 남은 휴가 일수를 계산합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "employee_id": {
                                "type": "string",
                                "description": "직원 ID"
                            },
                            "year": {
                                "type": "integer",
                                "description": "조회할 연도"
                            }
                        },
                        "required": ["employee_id"]
                    }
                }
            }
        ]
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        LLM에 전달할 형식으로 도구 목록을 반환합니다.
        
        Returns:
            List[Dict]: OpenAI 함수 호출 형식의 도구 목록
        """
        if not self._tools:
            return self._get_default_tools()
        return self._tools
    
    def get_tool_by_name(self, name: str) -> Dict[str, Any] | None:
        """
        도구 이름으로 특정 도구를 찾습니다.
        
        Args:
            name: 도구 이름
            
        Returns:
            Dict | None: 도구 정보 또는 None
        """
        for tool in self._tools:
            if tool.get("function", {}).get("name") == name:
                return tool
        
        # 기본 도구에서 검색
        for tool in self._get_default_tools():
            if tool.get("function", {}).get("name") == name:
                return tool
        
        return None


# 싱글톤 인스턴스
_inventory_instance: ToolInventory | None = None


def get_inventory() -> ToolInventory:
    """
    ToolInventory 싱글톤 인스턴스를 반환합니다.
    """
    global _inventory_instance
    if _inventory_instance is None:
        _inventory_instance = ToolInventory()
    return _inventory_instance
