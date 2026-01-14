"""
agent_loop_api_server.py - 메인 서버

클라이언트 기반 REST API 승인 방식의 에이전트 서버입니다.
도구 실행 전 클라이언트의 명시적 승인을 요구합니다.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

# 스크립트 위치를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 설정 로드
CONFIG_PATH = (Path(__file__).parent / "agent_loop_config" / "agent_loop_config.json").resolve()

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# 로깅 설정 (파일만, DB 없음)
LOG_FILE = (Path(__file__).parent / config["logging"]["file"]).resolve()
logging.basicConfig(
    level=getattr(logging, config["logging"]["level"]),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("agent_loop_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행"""
    logger.info("🚀 Agent Loop API Server starting...")
    logger.info(f"   Listening on http://{config['agent']['host']}:{config['agent']['port']}")
    logger.info(f"   LLM: {config['llm']['provider']} ({config['llm']['model']})")
    yield
    logger.info("🛑 Agent Loop API Server stopped")


# FastAPI 앱 생성
app = FastAPI(
    title="Agent Loop API Server",
    description="클라이언트 기반 REST API 승인 방식의 에이전트 서버",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

# 라우터 등록
from agent_loop_api_routes import router
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    import signal
    
    def signal_handler(sig, frame):
        print("\n🛑 종료 신호 수신. 서버를 정상 종료합니다...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    config_uvicorn = uvicorn.Config(
        app,
        host=config["agent"]["host"],
        port=config["agent"]["port"],
        loop="asyncio",
        timeout_graceful_shutdown=5
    )
    server = uvicorn.Server(config_uvicorn)
    
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n🛑 키보드 인터럽트. 서버를 종료합니다...")
    finally:
        print("✅ 서버가 정상 종료되었습니다.")
