"""
mcp_tools.py - 실제 실행될 개별 도구 정의

MCP 서버에서 호출 가능한 실제 도구(함수)들을 정의합니다.
각 도구는 Void(MCP Client)를 통해 호출되어 실제 작업을 수행합니다.
"""

import json
import sqlite3
import logging
from pathlib import Path
import sys

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))
from typing import Dict, Any, List, Optional
from datetime import datetime, date

logger = logging.getLogger(__name__)

# 설정 파일 로드
CONFIG_PATH = Path(__file__).parent / "mcp_config" / "mcp_config.json"

def load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        print(f"[Config] 설정 파일 로드 실패: {e}")
        return {"database": {"path": "../db/mcp_data.db"}}

config = load_config()

# 데이터베이스 경로 (설정 파일 기반)
DB_PATH = Path(__file__).parent / config["database"]["path"]


def ensure_database():
    """데이터베이스 및 샘플 데이터 초기화"""
    DB_PATH.parent.mkdir(exist_ok=True, parents=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 문서 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 직원 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            hire_date DATE,
            position TEXT
        )
    """)
    
    # 휴가 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vacations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT,
            year INTEGER,
            total_days INTEGER,
            used_days INTEGER,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    """)
    
    # 샘플 데이터 삽입 (이미 있으면 스킵)
    cursor.execute("SELECT COUNT(*) FROM documents")
    if cursor.fetchone()[0] == 0:
        sample_docs = [
            ("신입사원 휴가 규정", "입사 1년 미만 직원은 월 1회 유급 휴가를 사용할 수 있습니다. 입사 1년 이상 직원은 연간 15일의 유급 휴가가 부여됩니다.", "인사"),
            ("재택근무 지침", "주 2회까지 재택근무가 가능합니다. 사전에 팀장 승인이 필요합니다.", "인사"),
            ("경비 청구 가이드", "출장 경비는 법인카드 사용을 원칙으로 합니다. 개인 카드 사용 시 영수증 제출 후 익월 급여에 포함됩니다.", "총무"),
            ("보안 정책", "사내 문서는 외부 클라우드에 저장할 수 없습니다. 모든 업무 파일은 사내 NAS에 보관해야 합니다.", "IT"),
        ]
        cursor.executemany(
            "INSERT INTO documents (title, content, category) VALUES (?, ?, ?)",
            sample_docs
        )
        
        sample_employees = [
            ("EMP001", "김철수", "개발팀", "2023-03-15", "주니어 개발자"),
            ("EMP002", "이영희", "인사팀", "2021-08-01", "대리"),
            ("EMP003", "박민수", "개발팀", "2024-11-01", "인턴"),
        ]
        cursor.executemany(
            "INSERT INTO employees (id, name, department, hire_date, position) VALUES (?, ?, ?, ?, ?)",
            sample_employees
        )
        
        sample_vacations = [
            ("EMP001", 2024, 15, 8),
            ("EMP002", 2024, 15, 12),
            ("EMP003", 2024, 5, 1),
        ]
        cursor.executemany(
            "INSERT INTO vacations (employee_id, year, total_days, used_days) VALUES (?, ?, ?, ?)",
            sample_vacations
        )
    
    conn.commit()
    conn.close()
    logger.info(f"[Tools] 데이터베이스 초기화 완료: {DB_PATH}")


# ============================================================
# 도구 함수 정의
# ============================================================

def search_docs(query: str) -> Dict[str, Any]:
    """
    회사 문서에서 정보를 검색합니다.
    
    Args:
        query: 검색할 키워드 또는 질문
        
    Returns:
        Dict: 검색 결과
    """
    logger.info(f"[Tools] search_docs 실행: query='{query}'")
    
    ensure_database()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 키워드 검색 (제목 또는 내용에서)
    cursor.execute("""
        SELECT id, title, content, category 
        FROM documents 
        WHERE title LIKE ? OR content LIKE ?
    """, (f"%{query}%", f"%{query}%"))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "category": row[3]
        })
    
    conn.close()
    
    logger.info(f"[Tools] search_docs 결과: {len(results)}건 발견")
    
    return {
        "success": True,
        "query": query,
        "count": len(results),
        "results": results
    }


def get_employee_info(employee_id: str) -> Dict[str, Any]:
    """
    직원 정보를 조회합니다.
    
    Args:
        employee_id: 직원 ID
        
    Returns:
        Dict: 직원 정보
    """
    logger.info(f"[Tools] get_employee_info 실행: employee_id='{employee_id}'")
    
    ensure_database()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, department, hire_date, position 
        FROM employees 
        WHERE id = ?
    """, (employee_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        # 근속 기간 계산
        hire_date = datetime.strptime(row[3], "%Y-%m-%d").date()
        today = date.today()
        tenure_days = (today - hire_date).days
        tenure_years = tenure_days // 365
        
        employee_info = {
            "id": row[0],
            "name": row[1],
            "department": row[2],
            "hire_date": row[3],
            "position": row[4],
            "tenure_years": tenure_years,
            "tenure_days": tenure_days
        }
        
        logger.info(f"[Tools] get_employee_info 결과: {employee_info['name']} 발견")
        
        return {
            "success": True,
            "employee": employee_info
        }
    else:
        logger.warning(f"[Tools] get_employee_info: 직원을 찾을 수 없음")
        return {
            "success": False,
            "error": f"직원 ID '{employee_id}'를 찾을 수 없습니다"
        }


def calculate_vacation_days(
    employee_id: str, 
    year: Optional[int] = None
) -> Dict[str, Any]:
    """
    직원의 남은 휴가 일수를 계산합니다.
    
    Args:
        employee_id: 직원 ID
        year: 조회할 연도 (기본값: 현재 연도)
        
    Returns:
        Dict: 휴가 정보
    """
    if year is None:
        year = date.today().year
        
    logger.info(f"[Tools] calculate_vacation_days 실행: employee_id='{employee_id}', year={year}")
    
    ensure_database()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 직원 정보 확인
    cursor.execute("SELECT name FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone()
    
    if not employee:
        conn.close()
        logger.warning(f"[Tools] calculate_vacation_days: 직원을 찾을 수 없음")
        return {
            "success": False,
            "error": f"직원 ID '{employee_id}'를 찾을 수 없습니다"
        }
    
    # 휴가 정보 조회
    cursor.execute("""
        SELECT total_days, used_days 
        FROM vacations 
        WHERE employee_id = ? AND year = ?
    """, (employee_id, year))
    
    vacation = cursor.fetchone()
    conn.close()
    
    if vacation:
        total_days = vacation[0]
        used_days = vacation[1]
        remaining_days = total_days - used_days
        
        result = {
            "success": True,
            "employee_id": employee_id,
            "employee_name": employee[0],
            "year": year,
            "total_days": total_days,
            "used_days": used_days,
            "remaining_days": remaining_days
        }
        
        logger.info(f"[Tools] calculate_vacation_days 결과: 잔여 {remaining_days}일")
        return result
    else:
        logger.warning(f"[Tools] calculate_vacation_days: {year}년 휴가 정보 없음")
        return {
            "success": False,
            "error": f"{year}년 휴가 정보가 없습니다"
        }



def get_all_employees() -> Dict[str, Any]:
    """
    모든 직원의 목록을 조회합니다.
    
    Returns:
        Dict: 직원 목록
    """
    logger.info(f"[Tools] get_all_employees 실행")
    
    ensure_database()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, department, position 
        FROM employees
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            "id": row[0],
            "name": row[1],
            "department": row[2],
            "position": row[3]
        })
        
    logger.info(f"[Tools] get_all_employees 결과: {len(employees)}명 발견")
    
    return {
        "success": True,
        "count": len(employees),
        "employees": employees
    }


# 도구 레지스트리
TOOL_REGISTRY: Dict[str, callable] = {
    "search_docs": search_docs,
    "get_employee_info": get_employee_info,
    "get_all_employees": get_all_employees,
    "calculate_vacation_days": calculate_vacation_days,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    도구를 실행합니다.
    
    Args:
        tool_name: 실행할 도구 이름
        arguments: 도구에 전달할 인자
        
    Returns:
        Dict: 실행 결과
    """
    logger.info(f"[Tools] 도구 실행 요청: {tool_name}")
    logger.debug(f"[Tools] 인자: {json.dumps(arguments, ensure_ascii=False)}")
    
    if tool_name not in TOOL_REGISTRY:
        logger.error(f"[Tools] 알 수 없는 도구: {tool_name}")
        return {
            "success": False,
            "error": f"알 수 없는 도구: {tool_name}"
        }
    
    try:
        result = TOOL_REGISTRY[tool_name](**arguments)
        logger.info(f"[Tools] 도구 실행 완료: {tool_name}")
        return result
        
    except Exception as e:
        logger.error(f"[Tools] 도구 실행 실패: {e}")
        return {
            "success": False,
            "error": str(e)
        }
