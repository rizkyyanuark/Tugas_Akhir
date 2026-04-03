import weaviate
import logging

logging.basicConfig(level=logging.INFO)

print("Trying connect_to_local...")
try:
    client = weaviate.connect_to_local(host="127.0.0.1", port=8081)
    print("Success! Client ready:", client.is_ready())
    client.close()
except Exception as e:
    print("Local error:", e)

print("\nTrying connect_to_custom to public IP...")
try:
    client = weaviate.connect_to_custom(
        http_host="54.236.131.70",
        http_port=80,
        http_secure=False,
        grpc_host="54.236.131.70",
        grpc_port=50051,
        grpc_secure=False
    )
    print("Success! Client ready:", client.is_ready())
    client.close()
except Exception as e:
    print("Custom IP error:", e)
