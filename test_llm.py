# test_llm.py
"""
MerchAI v6 — Quick LLM Connection Test
Run this to verify your OpenRouter API key is working.

Usage:
    python test_llm.py
"""

import os
from openrouter import OpenRouter

# ── Load from .env if available ──────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[test_llm] Loaded .env file")
except ImportError:
    pass

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

if not API_KEY:
    print("❌ OPENROUTER_API_KEY not set.")
    print("   Set it in .env or export OPENROUTER_API_KEY=sk-or-v1-...")
    exit(1)

print(f"[test_llm] API key found: {API_KEY[:12]}...")
print("[test_llm] Sending test message to OpenRouter...")

try:
    with OpenRouter(api_key=API_KEY) as client:
        response = client.chat.send(
            model="inclusionai/ling-2.6-flash:free",
            messages=[
                {
                    "role": "system",
                    "content": "You are MerchAI Assistant. Reply in exactly one sentence."
                },
                {
                    "role": "user",
                    "content": "Hello! Are you working correctly?"
                }
            ]
        )
        reply = response.choices[0].message.content
        print(f"\n✅ Connection successful!")
        print(f"   Model response: {reply}")

except Exception as e:
    print(f"\n❌ Connection failed: {e}")
    print("   Check your API key at https://openrouter.ai/keys")