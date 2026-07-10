# test_llm.py
"""
MerchAI v6 — Quick Groq API Connection Test
Run this to verify your Groq API key is working.

Usage:
    python test_llm.py
"""

import os
import requests

# ── Load from .env if available ──────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[test_llm] Loaded .env file")
except ImportError:
    pass

API_KEY = os.environ.get("GROQ_API_KEY") or "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"

if not API_KEY or API_KEY == "your_groq_api_key_here":
    print("[ERROR] Groq API key not set.")
    print("   Please edit the GROQ_API_KEY variable in your .env file:")
    print("   Example: GROQ_API_KEY=gsk-...")
    exit(1)

print(f"[test_llm] API key found: {API_KEY[:12]}...")
print("[test_llm] Sending test message to Groq API...")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
payload = {
    "model": model,
    "messages": [
        {
            "role": "system",
            "content": "You are MunimAI Assistant. Reply in exactly one sentence."
        },
        {
            "role": "user",
            "content": "Hello! Are you working correctly?"
        }
    ],
    "max_tokens": 100,
    "temperature": 0.7
}

try:
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=15
    )
    
    if response.status_code == 200:
        reply = response.json()["choices"][0]["message"]["content"]
        print("\n[SUCCESS] Connection successful!")
        print(f"   Model used: {model}")
        print(f"   Response: {reply}")
    else:
        print(f"\n[ERROR] Connection failed with Status Code {response.status_code}: {response.text}")
        print("   Check your API key and billing at https://console.groq.com/")

except Exception as e:
    print(f"\n[ERROR] Connection failed: {e}")
    print("   Check your internet connection and API key configuration.")