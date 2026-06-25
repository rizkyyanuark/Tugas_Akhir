import os
import requests
import json
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

api_key = os.getenv("SILICONFLOW_API_KEY")
url = "https://api.siliconflow.com/v1/user/info"
headers = {
    "Authorization": f"Bearer {api_key}"
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print("Raw Response:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print("Failed with error:", e)
