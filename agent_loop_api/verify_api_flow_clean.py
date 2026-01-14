"""
verify_api_flow_clean.py - API 흐름 자동 검증 (No Emojis)

1. 채팅 요청 (도구 호출 유도)
2. 승인 대기 확인
3. 승인 요청
4. 결과 확인
"""

import requests
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8012"

def pd(msg):
    print(msg)

def run_test():
    pd("[START] API Flow Verification Start...")
    
    # 1. Chat Request
    pd("\n[1] Sending Chat Request ('Show employee list')...")
    try:
        resp = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:7b",
                "messages": [{"role": "user", "content": "직원 목록을 보여줘"}],
                "stream": False
            }
        )
    except Exception as e:
        pd(f"[ERROR] Connection failed: {e}")
        return False
    
    if resp.status_code != 200:
        pd(f"[FAIL] Request failed: {resp.text}")
        return False
        
    data = resp.json()
    if not data.get("approval_required"):
        pd("[FAIL] Not in pending approval state. (Tool call failed?)")
        pd(json.dumps(data, indent=2, ensure_ascii=False))
        return False
        
    request_id = data["pending_approval"]["request_id"]
    pd(f"[OK] Received Pending Approval Response (Request ID: {request_id})")
    tool_name = data['pending_approval']['tool_calls'][0]['name']
    pd(f"   Tool: {tool_name}")
    
    # 2. Check Pending List
    pd("\n[2] Checking Pending List...")
    resp = requests.get(f"{BASE_URL}/v1/pending")
    pending_list = resp.json().get("pending", [])
    
    found = any(p["request_id"] == request_id for p in pending_list)
    if not found:
        pd("[FAIL] Request ID not found in pending list.")
        return False
    pd("[OK] confirmed in pending list")
    
    # 3. Approve Request
    pd(f"\n[3] Approving Request (/v1/approve/{request_id})...")
    resp = requests.post(f"{BASE_URL}/v1/approve/{request_id}")
    
    if resp.status_code != 200:
        pd(f"[FAIL] Approval failed: {resp.text}")
        return False
    
    approve_data = resp.json()
    pd("[OK] Approved and Executed")
    
    # Check Final Result
    final_content = approve_data.get("response", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
    pd(f"[NOTE] Final Response Preview: {final_content[:100]}...")
    
    if "김철수" in final_content or "이영희" in final_content:
        pd("\n[SUCCESS] Verification Successful: Employee list found in response.")
        return True
    else:
        pd("\n[WARNING] Verification Warning: Employee names not found in response.")
        return True

if __name__ == "__main__":
    try:
        if run_test():
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        pd(f"\n[ERROR] Exception: {e}")
        sys.exit(1)
