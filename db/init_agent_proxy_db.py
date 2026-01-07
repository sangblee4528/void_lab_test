import sqlite3
from pathlib import Path
import sys

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))

# DB 경로 설정
DB_PATH = Path(__file__).parent / "agent_proxy_data.db"

def init_agent_proxy_db():
    print(f"🚀 Agent Proxy 데이터베이스 초기화 시작: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 테이블 삭제 (초기화용)
    cursor.execute("DROP TABLE IF EXISTS agent_logs")
    
    # 2. 테이블 생성
    cursor.execute("""
        CREATE TABLE agent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            request_id TEXT,
            message TEXT,
            details TEXT
        )
    """)
    
    # 3. 샘플 데이터 주입
    sample_logs = [
        ("INIT-A01", "Agent Proxy Server Initialized", "Database connected"),
        ("INIT-A02", "MCP Client Ready", "SSE session link established"),
    ]
    cursor.executemany("INSERT INTO agent_logs (request_id, message, details) VALUES (?, ?, ?)", sample_logs)
    
    conn.commit()
    conn.close()
    print("✅ Agent Proxy 데이터베이스 초기화 및 샘플 데이터 주입 완료!")

if __name__ == "__main__":
    init_agent_proxy_db()
