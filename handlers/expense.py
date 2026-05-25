import uuid
import logging
from datetime import date
from openai import AuthenticationError, APIConnectionError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services import ai_client
from config import CATEGORIES

logger = logging.getLogger(__name__)


def _build_confirm_card(pending: dict) -> tuple[str, InlineKeyboardMarkup]:
    amount = pending["amount"]
    description = pending["description"]
    note = pending["note"] or "—"
    exp_date = pending["date"]
    suggested = pending["suggested_category"]

    text = (
        f"*New Expense*\n\n"
        f"Amount:       RM {amount:.2f}\n"
        f"Description:  {description}\n"
        f"Note:         {note}\n"
        f"Date:         {exp_date}\n\n"
        f"_Tap a category to save:_"
    )

    uid = pending["uuid"]
    buttons = []
    row = []
    for cat in CATEGORIES:
        label = f"{cat} ✓" if cat == suggested else cat
        row.append(InlineKeyboardButton(label, callback_data=f"cat_select:{uid}:{cat}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return text, InlineKeyboardMarkup(buttons)


async def handle_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    logger.info("[MSG] user_id=%s username=%s | %r", user.id, user.username, text)
    await update.message.chat.send_action("typing")

    try:
        expenses = ai_client.parse_expenses(text)
    except AuthenticationError:
        logger.error("KIMI API authentication failed — check KIMI_API_KEY in .env")
        await update.message.reply_text(
            "⚠️ AI service authentication failed. Please check that `KIMI_API_KEY` in your `.env` file is correct."
        )
        return
    except APIConnectionError as e:
        logger.error("KIMI API connection error: %s", e)
        await update.message.reply_text("⚠️ Could not reach the AI service. Please try again.")
        return

    if not expenses:
        await update.message.reply_text(
            "I couldn't find an expense in that message.\n"
            "Try: _lunch 15.50 at mamak_ or _grab to office 8.50_",
            parse_mode="Markdown",
        )
        return

    today = date.today().isoformat()
    sent = 0

    for exp in expenses:
        try:
            amount = float(exp["amount"])
        except (KeyError, ValueError, TypeError):
            continue
        if amount <= 0:
            continue

        description = str(exp.get("description", "Expense"))
        note = str(exp.get("note", ""))
        exp_date = str(exp.get("date") or today)

        suggested = ai_client.suggest_category(description, amount)

        uid = uuid.uuid4().hex[:8]
        context.user_data[uid] = {
            "uuid": uid,
            "amount": amount,
            "description": description,
            "note": note,
            "date": exp_date,
            "suggested_category": suggested,
        }

        msg_text, keyboard = _build_confirm_card(context.user_data[uid])
        await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=keyboard)
        sent += 1

    if sent == 0:
        await update.message.reply_text("Couldn't parse a valid amount. Please try again.")
