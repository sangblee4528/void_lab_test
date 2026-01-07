#!/usr/bin/env python3
"""
mcp_tools_runner.py - CLI 도구 실행기 (Plan B 지원용)

프록시가 생성한 쉘 명령어를 받아서 실제 mcp_tools.py의 함수를 실행하는 어댑터입니다.
사용법: python mcp_tools_runner.py <tool_name> <json_args>
"""

import sys
import json
import logging
from pathlib import Path

# 현재 디렉토리를 모듈 검색 경로에 추가 (mcp_tools import를 위해)
current_dir = Path(__file__).parent
sys.path.append(str(current_dir))

# mcp_server 디렉토리에서 실행될 경우를 대비
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

try:
    from mcp_tools import execute_tool, TOOL_REGISTRY
except ImportError:
    # 만약 mcp_tools를 찾지 못하면, 상위 디렉토리(루트)에서 실행된 경우일 수 있음
    # 하지만 위에서 path를 추가했으므로 웬만하면 되어야 함.
    print(f"Error: Could not import mcp_tools. sys.path: {sys.path}")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(level=logging.ERROR) # 에러만 출력 (결과는 stdout으로 깔끔하게)

def main():
    if len(sys.argv) < 3:
        print("Usage: python mcp_tools_runner.py <tool_name> <json_arguments>")
        sys.exit(1)

    tool_name = sys.argv[1]
    json_args_str = sys.argv[2]

    try:
        args = json.loads(json_args_str)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON arguments: {json_args_str}")
        sys.exit(1)

    # 도구 실행
    if tool_name not in TOOL_REGISTRY:
        print(f"Error: Unknown tool '{tool_name}'")
        sys.exit(1)

    try:
        result = execute_tool(tool_name, args)
        # 결과 출력 (JSON으로 예쁘게)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error executing tool: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
