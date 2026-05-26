import re
import uuid
import logging
from datetime import date, timedelta
from openai import AuthenticationError, APIConnectionError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services import ai_client
from config import CATEGORIES

logger = logging.getLogger(__name__)

_DATE_FORMAT_HINT = "`YYYY-MM-DD`, `DD/MM/YYYY`, `today`, or `yesterday`"


def _parse_date_input(text: str) -> str | None:
    t = text.strip()
    lower = t.lower()
    if lower == "today":
        return date.today().isoformat()
    if lower == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if lower in ("2 days ago", "day before yesterday"):
        return (date.today() - timedelta(days=2)).isoformat()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
        try:
            date.fromisoformat(t)
            return t
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{4}|\d{2}))?$", t)
    if m:
        day, month_n, year_s = m.groups()
        if year_s is None:
            yr = date.today().year
        elif len(year_s) == 2:
            yr = 2000 + int(year_s)
        else:
            yr = int(year_s)
        try:
            return date(yr, int(month_n), int(day)).isoformat()
        except ValueError:
            return None
    return None


def _parse_amount(text: str) -> float | None:
    t = re.sub(r"[^\d.,\-]", "", text.strip())
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _build_confirm_card(pending: dict, currency: str = "RM") -> tuple[str, InlineKeyboardMarkup]:
    amount = pending["amount"]
    description = pending["description"]
    note = pending["note"] or "—"
    exp_date = pending["date"]
    suggested = pending["suggested_category"]

    text = (
        f"*New Expense*\n\n"
        f"Amount:       {currency} {amount:.2f}\n"
        f"Description:  {description}\n"
        f"Note:         {note}\n"
        f"Date:         {exp_date}\n\n"
        f"_Tap a category to save:_"
    )

    uid = pending["uuid"]
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    two_days_str = (date.today() - timedelta(days=2)).isoformat()

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

    # Date quick-pick row
    date_row = []
    for label, d in [("Today", today_str), ("Yesterday", yesterday_str), ("2d Ago", two_days_str)]:
        btn_label = f"📅 {label} ✓" if exp_date == d else f"📅 {label}"
        date_row.append(InlineKeyboardButton(btn_label, callback_data=f"date_set:{uid}:{d}"))
    buttons.append(date_row)
    buttons.append([InlineKeyboardButton("📅 Enter date…", callback_data=f"date_custom:{uid}")])

    return text, InlineKeyboardMarkup(buttons)


def _build_edit_card(row, currency: str = "RM") -> tuple[str, InlineKeyboardMarkup]:
    note = row["note"] or "—"
    text = (
        f"*Edit Expense #{row['id']}*\n\n"
        f"Date:         {row['date']}\n"
        f"Category:     {row['category']}\n"
        f"Description:  {row['description']}\n"
        f"Note:         {note}\n"
        f"Amount:       {currency} {row['amount']:.2f}\n\n"
        f"_Tap a field to edit:_"
    )
    eid = row["id"]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Amount", callback_data=f"edit_field:{eid}:amount"),
            InlineKeyboardButton("✏️ Date", callback_data=f"edit_field:{eid}:date"),
        ],
        [
            InlineKeyboardButton("✏️ Description", callback_data=f"edit_field:{eid}:description"),
            InlineKeyboardButton("✏️ Note", callback_data=f"edit_field:{eid}:note"),
        ],
        [
            InlineKeyboardButton("🏷 Category", callback_data=f"edit_field:{eid}:category"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"edit_cancel:{eid}"),
        ],
    ])
    return text, keyboard


async def handle_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    currency = context.bot_data.get("currency", "RM")

    # ── Intercept: waiting for custom date input for a pending expense ─────────
    waiting_uid = context.user_data.get("waiting_for_date_uid")
    if waiting_uid and waiting_uid in context.user_data:
        pending = context.user_data[waiting_uid]
        parsed = _parse_date_input(text)
        if parsed:
            pending["date"] = parsed
            context.user_data.pop("waiting_for_date_uid", None)
            msg_text, keyboard = _build_confirm_card(pending, currency)
            prompt_msg_id = context.user_data.pop("date_prompt_msg_id", None)
            prompt_chat_id = context.user_data.pop("date_prompt_chat_id", None)
            if prompt_msg_id and prompt_chat_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=prompt_chat_id,
                        message_id=prompt_msg_id,
                        text=msg_text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                    await update.message.delete()
                    return
                except Exception:
                    pass
            await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await update.message.reply_text(
                f"Invalid date. Use {_DATE_FORMAT_HINT}.",
                parse_mode="Markdown",
            )
        return

    # ── Intercept: waiting for a text field value for an edit ─────────────────
    edit_state = context.user_data.get("waiting_for_edit")
    if edit_state:
        expense_id = edit_state["expense_id"]
        field = edit_state["field"]
        db = context.bot_data["db"]

        value: str | float = text
        if field == "amount":
            try:
                value = _parse_amount(text)
                if value is None or value <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("Invalid amount. Enter a positive number (e.g. `15.50`).", parse_mode="Markdown")
                return
        elif field == "date":
            value = _parse_date_input(text)
            if not value:
                await update.message.reply_text(
                    f"Invalid date. Use {_DATE_FORMAT_HINT}.", parse_mode="Markdown"
                )
                return

        db.update_expense(expense_id, **{field: value})
        context.user_data.pop("waiting_for_edit", None)

        field_label = field.replace("_", " ").title()
        display_value = f"{currency} {value:.2f}" if field == "amount" else str(value)

        prompt_msg_id = edit_state.get("prompt_msg_id")
        prompt_chat_id = edit_state.get("prompt_chat_id")
        row = db.get_expense(expense_id)
        success_text = f"✅ Expense #{expense_id} updated: *{field_label}* → {display_value}"
        if prompt_msg_id and prompt_chat_id and row:
            from handlers.expense import _build_edit_card
            card_text, card_kb = _build_edit_card(row, currency)
            try:
                await context.bot.edit_message_text(
                    chat_id=prompt_chat_id,
                    message_id=prompt_msg_id,
                    text=card_text,
                    parse_mode="Markdown",
                    reply_markup=card_kb,
                )
                await update.message.reply_text(success_text, parse_mode="Markdown")
                await update.message.delete()
                return
            except Exception:
                pass
        await update.message.reply_text(success_text, parse_mode="Markdown")
        return

    # ── Normal expense parsing ─────────────────────────────────────────────────
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

        msg_text, keyboard = _build_confirm_card(context.user_data[uid], currency)
        await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=keyboard)
        sent += 1

    if sent == 0:
        await update.message.reply_text("Couldn't parse a valid amount. Please try again.")
