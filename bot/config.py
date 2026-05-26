import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
KIMI_API_KEY: str = os.environ["KIMI_API_KEY"]
DB_PATH: str = os.getenv("DB_PATH", "/data/budget_bot.db")
LOG_PATH: str = os.getenv("LOG_PATH", "/data/budget_bot.log")

CATEGORIES: list[str] = [
    "Food & Drinks",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Health",
    "Entertainment",
    "Education",
    "Personal Care",
    "Others",
]

BUDGET_WARN_PCT: float = 0.80
BUDGET_LIMIT_PCT: float = 1.00

CURRENCY_SYMBOL: str = os.getenv("CURRENCY_SYMBOL", "RM")
