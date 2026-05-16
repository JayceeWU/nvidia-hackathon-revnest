# Make it executable: chmod +x ~/revnest/tools/super_strategy_review.py

#!/usr/bin/env python3
import json
import os
import sys
from openai import OpenAI

FORBIDDEN_KEYS = {
    "guest_name",
    "guest_email",
    "reservation_id",
    "booking_history_csv",
    "raw_booking_history",
    "raw_revenue_table",
    "customer_data",
}

def contains_forbidden(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                return True, k
            bad, key = contains_forbidden(v)
            if bad:
                return True, key
    elif isinstance(obj, list):
        for item in obj:
            bad, key = contains_forbidden(item)
            if bad:
                return True, key
    return False, None

payload = json.loads(sys.stdin.read())
bad, key = contains_forbidden(payload)
if bad:
    print(json.dumps({
        "status": "blocked",
        "reason": f"Payload contains forbidden sensitive field: {key}"
    }, indent=2))
    sys.exit(2)

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"],
)

messages = [
    {
        "role": "system",
        "content": "You are a senior hotel revenue management advisor. Only use the sanitized summary provided. Do not ask for raw booking records."
    },
    {
        "role": "user",
        "content": "Review this sanitized demand summary and recommend a pricing strategy:\n" + json.dumps(payload, indent=2)
    }
]

resp = client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b",
    messages=messages,
    temperature=0.2,
    max_tokens=700,
)

print(json.dumps({
    "status": "approved",
    "model": "nvidia/nemotron-3-super-120b-a12b",
    "strategy_review": resp.choices[0].message.content
}, indent=2))