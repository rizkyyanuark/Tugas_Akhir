import os
import sys
from dotenv import load_dotenv
import weaviate
from weaviate.classes.config import Configure, Property, DataType

load_dotenv(override=True)

try:
    client = weaviate.connect_to_local(
        host="127.0.0.1", port=8081, skip_init_checks=True,
        headers={"X-HuggingFace-Api-Key": os.environ.get("HF_TOKEN", "")}
    )
    
    if client.collections.exists("TestProxyEndpoint"):
        client.collections.delete("TestProxyEndpoint")
        
    client.collections.create(
        name="TestProxyEndpoint",
        vectorizer_config=Configure.Vectorizer.text2vec_huggingface(
            endpoint_url="https://router.huggingface.co/hf-inference/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2",
        ),
        properties=[Property(name="text", data_type=DataType.TEXT)]
    )
    
    print("Collection created successfully.")
    
    col = client.collections.get("TestProxyEndpoint")
    # This should block and successfully insert, verifying the API path!
    uuid = col.data.insert({"text": "This is a test document to trigger huggingface endpoint."})
    print(f"Insertion successful! UUID: {uuid}")
    client.close()
except Exception as e:
    print("Failed:")
    import traceback
    traceback.print_exc()
