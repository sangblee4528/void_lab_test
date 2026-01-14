"""
agent_loop_api_tools.py - 도구 정의 및 실행

에이전트가 사용할 수 있는 네이티브 도구들을 정의합니다.
DB에서 데이터를 조회/수정하는 도구들이 포함됩니다.
"""

import sqlite3
import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

# DB 경로 설정
DB_PATH = (Path(__file__).parent / "db" / "agent_loop_data.db").resolve()


def init_database():
    """데이터베이스 초기화 및 테이블 생성"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # employees 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT,
            position TEXT,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # pending_requests 테이블 (승인 대기)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_requests (
            request_id TEXT PRIMARY KEY,
            tool_calls TEXT,
            messages TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 샘플 데이터 확인 및 삽입
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0:
        sample_data = [
            ("김철수", "개발팀", "시니어 개발자", "kim@example.com"),
            ("이영희", "디자인팀", "UI/UX 디자이너", "lee@example.com"),
            ("박민수", "개발팀", "주니어 개발자", "park@example.com"),
            ("정수진", "기획팀", "프로덕트 매니저", "jung@example.com"),
            ("최동현", "개발팀", "백엔드 개발자", "choi@example.com"),
        ]
        cursor.executemany(
            "INSERT INTO employees (name, department, position, email) VALUES (?, ?, ?, ?)",
            sample_data
        )
    
    conn.commit()
    conn.close()


# ============================================================
# 도구 함수 정의
# ============================================================

def get_all_employees() -> Dict[str, Any]:
    """모든 직원 목록을 조회합니다."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, department, position, email FROM employees")
        rows = cursor.fetchall()
        conn.close()
        
        employees = [
            {"id": r[0], "name": r[1], "department": r[2], "position": r[3], "email": r[4]}
            for r in rows
        ]
        return {"success": True, "employees": employees, "count": len(employees)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_employee_by_id(employee_id: int) -> Dict[str, Any]:
    """ID로 특정 직원을 조회합니다."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, department, position, email FROM employees WHERE id = ?",
            (employee_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "success": True,
                "employee": {"id": row[0], "name": row[1], "department": row[2], "position": row[3], "email": row[4]}
            }
        return {"success": False, "error": f"ID {employee_id}인 직원을 찾을 수 없습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def add_employee(name: str, department: str, position: str, email: str = "") -> Dict[str, Any]:
    """새 직원을 추가합니다."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO employees (name, department, position, email) VALUES (?, ?, ?, ?)",
            (name, department, position, email)
        )
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"success": True, "message": f"직원 '{name}'이 추가되었습니다.", "id": new_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_employees(keyword: str) -> Dict[str, Any]:
    """키워드로 직원을 검색합니다."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        like_pattern = f"%{keyword}%"
        cursor.execute(
            """SELECT id, name, department, position, email FROM employees 
               WHERE name LIKE ? OR department LIKE ? OR position LIKE ?""",
            (like_pattern, like_pattern, like_pattern)
        )
        rows = cursor.fetchall()
        conn.close()
        
        employees = [
            {"id": r[0], "name": r[1], "department": r[2], "position": r[3], "email": r[4]}
            for r in rows
        ]
        return {"success": True, "employees": employees, "count": len(employees)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_current_time() -> Dict[str, Any]:
    """현재 시간을 반환합니다."""
    now = datetime.now()
    return {
        "success": True,
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A")
    }


# ============================================================
# 도구 정의 (OpenAI 호환 형식)
# ============================================================

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "get_all_employees",
            "description": "회사의 모든 직원 목록을 조회합니다.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_by_id",
            "description": "ID로 특정 직원의 상세 정보를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "integer", "description": "조회할 직원의 ID"}
                },
                "required": ["employee_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_employee",
            "description": "새로운 직원을 추가합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "직원 이름"},
                    "department": {"type": "string", "description": "소속 부서"},
                    "position": {"type": "string", "description": "직책"},
                    "email": {"type": "string", "description": "이메일 주소 (선택)"}
                },
                "required": ["name", "department", "position"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_employees",
            "description": "키워드로 직원을 검색합니다. 이름, 부서, 직책에서 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "검색할 키워드"}
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "현재 날짜와 시간을 반환합니다.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]

# 도구 레지스트리 (이름 -> 함수 매핑)
TOOL_REGISTRY = {
    "get_all_employees": get_all_employees,
    "get_employee_by_id": get_employee_by_id,
    "add_employee": add_employee,
    "search_employees": search_employees,
    "get_current_time": get_current_time,
}


# 모듈 로드 시 DB 초기화
if not DB_PATH.exists():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
init_database()
