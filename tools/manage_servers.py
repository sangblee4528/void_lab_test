import os
import subprocess
import signal
import sys
import time
from pathlib import Path

# 현재 디렉토리 경로 추가
sys.path.append(str(Path(__file__).parent))

# 관리 대상 포트 정의
TARGET_PORTS = [3000, 8000, 8001]

# 서버 실행 명령어 정의
SERVERS = {
    "mcp": {
        "name": "MCP Server (SSE)",
        "port": 3000,
        "cwd": "mcp_server",
        "cmd": ["python", "mcp_hosts_sse.py"],
        "log": "mcp_server.log"
    },
    "proxy": {
        "name": "Proxy Server",
        "port": 8000,
        "cwd": "proxy_server",
        "cmd": ["python", "proxy_server.py"],
        "log": "proxy_server.log"
    }
}

def get_process_on_port(port):
    """지정된 포트를 점유 중인 프로세스 정보를 가져옵니다."""
    try:
        # lsof 명령어를 사용하여 포트 점유 확인
        # -t: PID만 출력, -i: 연관된 소켓 정보
        output = subprocess.check_output(["lsof", "-t", f"-i:{port}"], stderr=subprocess.STDOUT)
        pids = output.decode().strip().split('\n')
        
        results = []
        for pid in pids:
            if not pid: continue
            # PID로 프로세스 이름 확인
            cmd = subprocess.check_output(["ps", "-p", pid, "-o", "command="]).decode().strip()
            results.append({"pid": pid, "command": cmd})
        return results
    except subprocess.CalledProcessError:
        # 해당 포트를 점유 중인 프로세스가 없는 경우
        return []

def kill_process(pid):
    """지정된 PID의 프로세스를 종료합니다."""
    try:
        pid_int = int(pid)
        os.kill(pid_int, signal.SIGTERM)
        print(f"✅ PID {pid}에 종료 신호(SIGTERM)를 보냈습니다.")
        return True
    except Exception as e:
        try:
            # 강제 종료 시도
            os.kill(pid_int, signal.SIGKILL)
            print(f"⚠️ PID {pid}를 강제 종료(SIGKILL)했습니다.")
            return True
        except:
            print(f"❌ PID {pid} 종료 실패: {e}")
            return False

def start_server(key):
    """서버를 백그라운드에서 실행합니다."""
    info = SERVERS[key]
    print(f"🚀 {info['name']} 시작 중...")
    
    # 작업 디렉토리 설정 (프로젝트 루트 기준)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cwd = os.path.join(project_root, info['cwd'])
    
    # 로그 파일 설정
    log_path = os.path.join(cwd, info['log'])
    
    try:
        with open(log_path, "a") as log_file:
            process = subprocess.Popen(
                info['cmd'],
                cwd=cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            print(f"   PID: {process.pid}, Log: {info['cwd']}/{info['log']}")
            return True
    except Exception as e:
        print(f"❌ {info['name']} 시작 실패: {e}")
        return False

def main():
    print("============================================================")
    print("🤖 Void Lab Test 서버 프로세스 관리자")
    print("============================================================")
    
    found_any = False
    killed_any = False
    
    # 1. 프로세스 확인 및 종료
    for port in TARGET_PORTS:
        processes = get_process_on_port(port)
        
        if not processes:
            print(f"📌 포트 {port}: 사용 중인 프로세스 없음")
            continue
            
        found_any = True
        print(f"🔥 포트 {port}가 다음 프로세스에 의해 사용 중입니다:")
        
        for proc in processes:
            print(f"   - PID: {proc['pid']}")
            print(f"     CMD: {proc['command']}")
            
            answer = input(f"   👉 이 프로세스를 종료하시겠습니까? (y/N): ").lower()
            
            if answer == 'y':
                if kill_process(proc['pid']):
                    killed_any = True
            else:
                print(f"   ⏭️ 프로세스를 유지합니다.")
        print("-" * 60)

    if not found_any:
        print("\n✅ 현재 관리 대상 포트 중 활성화된 서버가 없습니다.")
    
    # 2. 서버 재시작 여부 확인
    print("\n" + "=" * 60)
    print("🔄 서버 재시작 관리")
    print("=" * 60)
    
    restart = input("👉 MCP 서버와 Proxy 서버를 순서대로 실행하시겠습니까? (y/N): ").lower()
    
    if restart == 'y':
        # 1. MCP 서버 시작
        mcp_running = get_process_on_port(3000)
        if mcp_running:
            print(f"⚠️ MCP 서버(Port 3000)가 이미 실행 중입니다.")
        else:
            if start_server("mcp"):
                print("   ⏳ MCP 서버 안정화를 위해 2초 대기...")
                time.sleep(2)
        
        # 2. Proxy 서버 시작
        proxy_running = get_process_on_port(8000)
        if proxy_running:
            print(f"⚠️ Proxy 서버(Port 8000)가 이미 실행 중입니다.")
        else:
            start_server("proxy")
            
        print("\n✅ 모든 서버 실행 작업이 완료되었습니다.")
        print("   (로그는 각 서버 디렉토리의 .log 파일을 확인하세요)")
    else:
        print("\n서버를 실행하지 않고 종료합니다.")

    print("\n관리 도구를 종료합니다.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 사용자에 의해 중단되었습니다.")
        sys.exit(0)
