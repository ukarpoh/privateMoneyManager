import logging
from logging.handlers import TimedRotatingFileHandler
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from config import BOT_TOKEN, LOG_PATH
from services.database import Database
from handlers.expense import handle_expense
from handlers.commands import start, summary, recent, delete, budget, help_cmd
from handlers.callbacks import handle_callback

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_file_handler = TimedRotatingFileHandler(
    LOG_PATH,
    when="midnight",
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


def main():
    db = Database()
    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("recent", recent))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("budget", budget))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_expense))

    logging.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
