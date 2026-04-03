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
    
    # Try to create a collection with the new endpoint
    if client.collections.exists("TestProxyEndpoint"):
        client.collections.delete("TestProxyEndpoint")
        
    client.collections.create(
        name="TestProxyEndpoint",
        vectorizer_config=Configure.Vectorizer.text2vec_huggingface(
            endpoint_url="https://router.huggingface.co/hf-inference",
            model="sentence-transformers/all-MiniLM-L6-v2"
        ),
        properties=[Property(name="text", data_type=DataType.TEXT)]
    )
    
    print("Collection created successfully.")
    
    # Try inserting data to trigger the HF inference
    col = client.collections.get("TestProxyEndpoint")
    col.data.insert({"text": "This is a test document to trigger huggingface endpoint."})
    print("Insertion successful! The new router works!")
    client.close()
except Exception as e:
    print("Failed:")
    print(e)
