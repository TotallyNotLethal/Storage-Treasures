import base64
import json
import os
from io import BytesIO

from PIL import Image
import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_URL = "https://api.openai.com/v1/chat/completions"

def analyze_image(image_bytes, seen_items=None):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    seen_items = seen_items or []

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    width = height = None
    try:
        with Image.open(BytesIO(image_bytes)) as im:
            width, height = im.size
    except Exception:
        width = height = None

    size_hint = ""
    if width and height:
        size_hint = (
            f"Image resolution: {width}x{height}. "
            "Calculate bounding boxes relative to this size so that x/y/w/h are normalized between 0 and 1. "
            "Boxes may overlap when objects stack or occlude each other. "
            "Double-check coordinates stay within the image frame before returning.\n\n"
        )

    prompt = (
        "You are an expert storage auction appraiser working through multiple photos of the same auction.\n"
        "Treat this image as an incremental pass: only add NEW items that are not already identified from earlier photos.\n"
        "Existing items (do NOT repeat): "
        f"{', '.join(seen_items) if seen_items else 'none known yet'}.\n"
        "When describing items, remember objects seen in previous images so duplicates are excluded.\n"
        "If an object appears again, ignore it unless there is meaningful new detail to refine brand or pricing.\n\n"
        "First determine the image dimensions and place bounding boxes relative to the actual width and height so they stay on each object.\n"
        "Boxes may overlap if objects overlap in the photo.\n"
        f"{size_hint}"
        "Analyze this image and identify any additional distinct objects you can.\n"
        "For each NEW object:\n"
        "- name\n"
        "- brand (if visible or likely)\n"
        "- confidence (0–1)\n"
        "- estimated resale price range (low/high USD)\n"
        "- bounding box for where the object appears in the image as normalized coordinates {x,y,w,h} between 0 and 1.\n\n"
        "Return STRICT JSON only in this format:\n"
        "{\n"
        "  \"items\": [\n"
        "    {\"name\":\"\", \"brand\":\"\", \"confidence\":0.0, \"low\":0, \"high\":0, \"box\":{\"x\":0.0,\"y\":0.0,\"w\":0.0,\"h\":0.0}}\n"
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
