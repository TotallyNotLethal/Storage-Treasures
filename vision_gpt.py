import base64
import json
import os
import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_URL = "https://api.openai.com/v1/chat/completions"

def analyze_image(image_bytes):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = (
        "You are an expert storage auction appraiser.\n"
        "Analyze this image and identify as many distinct objects as you can.\n"
        "For each object:\n"
        "- name\n"
        "- brand (if visible or likely)\n"
        "- confidence (0–1)\n"
        "- estimated resale price range (low/high USD)\n\n"
        "Return STRICT JSON only in this format:\n"
        "{\n"
        "  \"items\": [\n"
        "    {\"name\":\"\", \"brand\":\"\", \"confidence\":0.0, \"low\":0, \"high\":0}\n"
        "  ]\n"
        "}"
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.2
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()

    content = r.json()["choices"][0]["message"]["content"]

    if not content:
        return {"items": []}

    content = content.strip()

    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()

    print("Identified:\n", content)

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print("JSON PARSE ERROR:", e)
        return {"items": []}
