import os
import requests
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

api_key = os.getenv("SILICONFLOW_API_KEY")
url = "https://api.siliconflow.com/v1/embeddings"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
data = {
    "model": "Qwen/Qwen3-Embedding-0.6B",
    "input": ["Hello world"]
}

print("Testing SiliconFlow connection with Qwen3...")
try:
    response = requests.post(url, headers=headers, json=data, timeout=10)
    print("Status code:", response.status_code)
    print("Response JSON:", response.json())
except Exception as e:
    print("Failed with error:", e)
