import sqlite3
from pathlib import Path
import sys

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))

# DB 경로 설정
DB_PATH = Path(__file__).parent / "proxy_data.db"

def init_proxy_db():
    print(f"🚀 Proxy 데이터베이스 초기화 시작: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 테이블 삭제 (초기화용)
    cursor.execute("DROP TABLE IF EXISTS proxy_logs")
    
    # 2. 테이블 생성
    cursor.execute("""
        CREATE TABLE proxy_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            level TEXT,
            message TEXT,
            request_id TEXT
        )
    """)
    
    # 3. 샘플 데이터 주입
    sample_logs = [
        ("INFO", "Proxy Server Started", "INIT-001"),
        ("INFO", "Ollama Connection Established", "INIT-002"),
        ("DEBUG", "Fetching tools from MCP server", "REQ-101"),
        ("INFO", "Successfully loaded 3 tools", "REQ-101"),
    ]
    cursor.executemany("INSERT INTO proxy_logs (level, message, request_id) VALUES (?, ?, ?)", sample_logs)
    
    conn.commit()
    conn.close()
    print("✅ Proxy 데이터베이스 초기화 및 샘플 데이터 주입 완료!")

if __name__ == "__main__":
    init_proxy_db()
