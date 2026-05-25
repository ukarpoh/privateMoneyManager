"""Quick script to verify KIMI API key is valid."""
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("KIMI_API_KEY", "")
if not api_key:
    print("ERROR: KIMI_API_KEY is not set in .env")
    exit(1)

print(f"Key loaded: {api_key[:8]}...{api_key[-4:]}  (length: {len(api_key)})")

from openai import OpenAI

client = OpenAI(api_key=api_key, base_url="https://api.moonshot.ai/v1")

try:
    response = client.chat.completions.create(
        model="kimi-k2.6",
        messages=[{"role": "user", "content": "say hello"}],
        max_tokens=10,
    )
    print("SUCCESS:", response.choices[0].message.content)
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
