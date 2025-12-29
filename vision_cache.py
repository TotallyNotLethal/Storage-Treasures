import hashlib
import json
import os

CACHE_DIR = "vision_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def get_cached(hash_id):
    path = os.path.join(CACHE_DIR, f"{hash_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def set_cached(hash_id, result):
    path = os.path.join(CACHE_DIR, f"{hash_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
