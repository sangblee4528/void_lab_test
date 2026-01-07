import sqlite3
import os
from pathlib import Path
import sys

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))

# DB 경로 설정
DB_PATH = Path(__file__).parent / "mcp_data.db"

def init_mcp_db():
    print(f"🚀 MCP 데이터베이스 초기화 시작: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 테이블 삭제 (초기화용)
    cursor.execute("DROP TABLE IF EXISTS documents")
    cursor.execute("DROP TABLE IF EXISTS employees")
    cursor.execute("DROP TABLE IF EXISTS vacations")
    
    # 2. 테이블 생성
    cursor.execute("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE employees (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT,
            hire_date DATE,
            position TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE vacations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT,
            year INTEGER,
            total_days INTEGER,
            used_days INTEGER,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    """)
    
    # 3. 샘플 데이터 주입
    sample_docs = [
        ("신입사원 휴가 규정", "입사 1년 미만 직원은 월 1회 유급 휴가를 사용할 수 있습니다. 입사 1년 이상 직원은 연간 15일의 유급 휴가가 부여됩니다.", "인사"),
        ("재택근무 지침", "주 2회까지 재택근무가 가능합니다. 사전에 팀장 승인이 필요합니다.", "인사"),
        ("경비 청구 가이드", "출장 경비는 법인카드 사용을 원칙으로 합니다. 개인 카드 사용 시 영수증 제출 후 익월 급여에 포함됩니다.", "총무"),
        ("보안 정책", "사내 문서는 외부 클라우드에 저장할 수 없습니다. 모든 업무 파일은 사내 NAS에 보관해야 합니다.", "IT"),
    ]
    cursor.executemany("INSERT INTO documents (title, content, category) VALUES (?, ?, ?)", sample_docs)
    
    sample_employees = [
        ("EMP001", "김철수", "개발팀", "2023-03-15", "주니어 개발자"),
        ("EMP002", "이영희", "인사팀", "2021-08-01", "대리"),
        ("EMP003", "박민수", "개발팀", "2024-11-01", "인턴"),
    ]
    cursor.executemany("INSERT INTO employees (id, name, department, hire_date, position) VALUES (?, ?, ?, ?, ?)", sample_employees)
    
    sample_vacations = [
        ("EMP001", 2024, 15, 8),
        ("EMP002", 2024, 15, 12),
        ("EMP003", 2024, 5, 1),
    ]
    cursor.executemany("INSERT INTO vacations (employee_id, year, total_days, used_days) VALUES (?, ?, ?, ?)", sample_vacations)
    
    conn.commit()
    conn.close()
    print("✅ MCP 데이터베이스 초기화 및 샘플 데이터 주입 완료!")

if __name__ == "__main__":
    init_mcp_db()
