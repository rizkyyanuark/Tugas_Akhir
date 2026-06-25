import os
import requests
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(r"c:\Users\rizky\Documents\GitHub\Tugas_Akhir\.env")
load_dotenv(env_path)

api_key = os.getenv("SILICONFLOW_API_KEY")
url = "https://api.siliconflow.com/v1/user/info"
headers = {
    "Authorization": f"Bearer {api_key}"
}

print("Checking SiliconFlow Account Info...")
try:
    response = requests.get(url, headers=headers, timeout=10)
    print("Status code:", response.status_code)
    if response.status_code == 200:
        data = response.json().get("data", {})
        print("\n=== Account Details ===")
        print("Username:", data.get("username"))
        print("Email:", data.get("email"))
        print("Balance (CNY):", data.get("balance"))
        print("Charge Balance (CNY):", data.get("chargeBalance"))
        print("Total Balance (CNY):", data.get("totalBalance"))
        print("Status:", data.get("status"))
    else:
        print("Error Response:", response.text)
except Exception as e:
    print("Failed with error:", e)
