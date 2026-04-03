from pymilvus import MilvusClient
import json

try:
    client = MilvusClient(uri="http://127.0.0.1:19530")
    print("Collections:", client.list_collections())
except Exception as e:
    print("Error:", e)
