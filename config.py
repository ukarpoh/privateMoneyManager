from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
KIMI_API_KEY = os.environ["KIMI_API_KEY"]
DB_PATH = os.getenv("DB_PATH", "/data/budget_bot.db")
LOG_PATH = os.getenv("LOG_PATH", "/data/budget_bot.log")

CATEGORIES = [
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

BUDGET_WARN_PCT = 0.80
BUDGET_LIMIT_PCT = 1.00

CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "RM")
