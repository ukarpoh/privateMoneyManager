import json
import logging
from datetime import date
from openai import OpenAI
from config import KIMI_API_KEY, CATEGORIES

logger = logging.getLogger(__name__)

client = OpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.ai/v1")
MODEL = "kimi-k2.6"

_PARSE_SYSTEM = """\
You are an expense parser for a personal budget bot.
Extract one or more expenses from the user's message.
Return a JSON array only — no prose, no markdown fences.
Each element must have exactly these keys:
  "amount"      : float (always positive)
  "description" : string (2-5 words, what was bought/paid for)
  "note"        : string (extra context like shop name, or "" if none)
  "date"        : string (ISO 8601 YYYY-MM-DD — use today if not mentioned)
Today's date is {today}.
If no valid expense found, return [].
"""

_CATEGORY_SYSTEM = (
    "You are a personal finance assistant. "
    "Given an expense description and amount, return the single most appropriate "
    "category from this list (return the exact name, nothing else):\n"
    + ", ".join(CATEGORIES)
)


def parse_expenses(text: str) -> list[dict]:
    today = date.today().isoformat()
    logger.info("[PARSE] Input: %r", text)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _PARSE_SYSTEM.format(today=today)},
            {"role": "user", "content": text},
        ],
    )
    raw = response.choices[0].message.content.strip()
    logger.info("[PARSE] Raw response: %s", raw)
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw)
        if not isinstance(result, list):
            logger.warning("[PARSE] Response was not a list, returning []")
            return []
        logger.info("[PARSE] Parsed %d expense(s): %s", len(result), result)
        return result
    except json.JSONDecodeError as e:
        logger.error("[PARSE] JSON decode failed: %s | raw was: %s", e, raw)
        return []


def suggest_category(description: str, amount: float) -> str:
    logger.info("[CATEGORY] Input: %r | amount: %s", description, amount)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _CATEGORY_SYSTEM},
            {"role": "user", "content": f"Description: {description}\nAmount: {amount}"},
        ],
    )
    suggested = response.choices[0].message.content.strip()
    result = suggested if suggested in CATEGORIES else "Others"
    logger.info("[CATEGORY] Response: %r → assigned: %s", suggested, result)
    return result
