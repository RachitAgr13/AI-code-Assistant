import requests
import json

response = requests.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "qwen2.5-coder:7b",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False
    }
)
print(response.status_code)
print(response.text)
