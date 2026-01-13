"""
native_loop_tools.py - MCP 서버 없이 에이전트가 직접 실행하는 도구 정의
"""

import json
import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, date

logger = logging.getLogger(__name__)

# 데이터베이스 경로 설정 (agent_native_loop_config와 동일한 위치를 바라보도록 설정)
DB_PATH = (Path(__file__).parent.parent / "db" / "agent_native_loop_data.db").resolve()
# 실제 서비스용 데이터 DB (mcp_data.db의 내용을 활용)
SERVICE_DB_PATH = (Path(__file__).parent.parent / "db" / "mcp_data.db").resolve()

def search_docs(query: str) -> Dict[str, Any]:
    """회사 문서에서 정보를 검색합니다."""
    logger.info(f"[NativeTools] search_docs 실행: query='{query}'")
    
    conn = sqlite3.connect(SERVICE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, content, category 
        FROM documents 
        WHERE title LIKE ? OR content LIKE ?
    """, (f"%{query}%", f"%{query}%"))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0], "title": row[1], "content": row[2], "category": row[3]
        })
    conn.close()
    return {"success": True, "query": query, "count": len(results), "results": results}

def get_employee_info(employee_id: str) -> Dict[str, Any]:
    """직원 정보를 조회합니다."""
    logger.info(f"[NativeTools] get_employee_info 실행: employee_id='{employee_id}'")
    
    conn = sqlite3.connect(SERVICE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, department, hire_date, position 
        FROM employees WHERE id = ?
    """, (employee_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        hire_date = datetime.strptime(row[3], "%Y-%m-%d").date()
        tenure_days = (date.today() - hire_date).days
        return {
            "success": True,
            "employee": {
                "id": row[0], "name": row[1], "department": row[2],
                "hire_date": row[3], "position": row[4],
                "tenure_years": tenure_days // 365, "tenure_days": tenure_days
            }
        }
    return {"success": False, "error": f"직원 ID '{employee_id}'를 찾을 수 없습니다"}

def get_all_employees() -> Dict[str, Any]:
    """모든 직원의 목록을 조회합니다."""
    logger.info(f"[NativeTools] get_all_employees 실행")
    
    conn = sqlite3.connect(SERVICE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, department, position FROM employees")
    
    rows = cursor.fetchall()
    conn.close()
    
    employees = [{"id": r[0], "name": r[1], "department": r[2], "position": r[3]} for r in rows]
    return {"success": True, "count": len(employees), "employees": employees}

def calculate_vacation_days(employee_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    """직원의 남은 휴가 일수를 계산합니다."""
    if year is None: year = date.today().year
    logger.info(f"[NativeTools] calculate_vacation_days 실행: id='{employee_id}', year={year}")
    
    conn = sqlite3.connect(SERVICE_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone()
    if not employee:
        conn.close()
        return {"success": False, "error": f"직원 ID '{employee_id}'를 찾을 수 없습니다"}
    
    cursor.execute("SELECT total_days, used_days FROM vacations WHERE employee_id = ? AND year = ?", (employee_id, year))
    vacation = cursor.fetchone()
    conn.close()
    
    if vacation:
        return {
            "success": True, "employee_id": employee_id, "employee_name": employee[0],
            "year": year, "total_days": vacation[0], "used_days": vacation[1],
            "remaining_days": vacation[0] - vacation[1]
        }
    return {"success": False, "error": f"{year}년 휴가 정보가 없습니다"}

def force_error(reason: str) -> Dict[str, Any]:
    """의도적으로 에러를 발생시켜 피드백 루프를 테스트합니다."""
    logger.info(f"[NativeTools] force_error 실행: reason='{reason}'")
    return {"success": False, "error": f"의도된 에러 발생: {reason}", "should_retry": True}

# OpenAI/Ollama 도구 규격 정의를 위한 메타데이터
NATIVE_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "회사 문서(규정, 가이드 등)에서 정보를 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색할 키워드"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_employees",
            "description": "회사의 모든 직원 목록을 가져옵니다.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_info",
            "description": "특정 직원의 상세 정보(부서, 입사일 등)를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "직원 ID (예: EMP001)"}
                },
                "required": ["employee_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_vacation_days",
            "description": "직원의 연도별 잔여 휴가 일수를 계산합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string", "description": "직원 ID"},
                    "year": {"type": "integer", "description": "조회 연도 (기본: 현재 연도)"}
                },
                "required": ["employee_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "force_error",
            "description": "의도적으로 에러를 발생시켜 피드백 루프를 테스트합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "에러 발생 이유"}
                },
                "required": ["reason"]
            }
        }
    }
]

# 실제 함수 매핑
NATIVE_TOOL_REGISTRY = {
    "search_docs": search_docs,
    "get_all_employees": get_all_employees,
    "get_employee_info": get_employee_info,
    "calculate_vacation_days": calculate_vacation_days,
    "force_error": force_error,
}
