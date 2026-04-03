import os
from dotenv import load_dotenv
import weaviate

load_dotenv(override=True)

print("Host from env:", os.environ.get("WEAVIATE_HOST"))
print("Port from env:", os.environ.get("WEAVIATE_PORT"))
print("HTTP_PROXY:", os.environ.get("HTTP_PROXY"))
print("HTTPS_PROXY:", os.environ.get("HTTPS_PROXY"))

try:
    host = os.environ.get("WEAVIATE_HOST", "127.0.0.1")
    port = int(os.environ.get("WEAVIATE_PORT", "8081"))
    
    print(f"Connecting to {host}:{port}")
    client = weaviate.connect_to_local(host=host, port=port)
    print("Success! Client ready:", client.is_ready())
    client.close()
except Exception as e:
    import traceback
    traceback.print_exc()
