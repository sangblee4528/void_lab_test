import requests
import json

url = "http://127.0.0.1:8011/v1/chat/completions"
headers = {"Content-Type": "application/json"}
payload = {
    "model": "qwen2.5-coder:7b",
    "messages": [{"role": "user", "content": "a.txt 확인해줘"}],
    "stream": False
}

try:
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error: {e}")
