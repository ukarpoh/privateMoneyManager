import logging
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.config import BUDGET_WARN_PCT, BUDGET_LIMIT_PCT, CATEGORIES

logger = logging.getLogger(__name__)

_EDIT_FIELD_LABELS = {
    "amount": "amount (e.g. `15.50`)",
    "description": "description",
    "note": "note (or send `-` to clear)",
    "date": "date (`YYYY-MM-DD`, `DD/MM/YYYY`, `today`, `yesterday`)",
}


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    db = context.bot_data["db"]
    today = date.today()
    currency = context.bot_data.get("currency", "RM")

    # ── Category selection: save new expense ──────────────────────────────────
    if data.startswith("cat_select:"):
        _, uid, category = data.split(":", 2)

        pending = context.user_data.get(uid)
        if not pending:
            await query.edit_message_text("This expense has already been saved.")
            return

        expense_id = db.add_expense(
            amount=pending["amount"],
            description=pending["description"],
            note=pending["note"],
            category=category,
            expense_date=pending["date"],
        )
        logger.info(
            "[SAVE] id=%s | %s | %.2f | %s | date=%s | note=%r",
            expense_id, pending["description"], pending["amount"],
            category, pending["date"], pending["note"],
        )

        del context.user_data[uid]

        warning = ""
        spent = db.get_category_monthly_total(category, today.year, today.month)
        limit = db.get_budget(category)
        if limit and limit > 0:
            pct = spent / limit
            if pct >= BUDGET_LIMIT_PCT:
                warning = f"\n\n🚨 *Over budget!* {category}: {currency} {spent:.2f} / {currency} {limit:.2f}"
            elif pct >= BUDGET_WARN_PCT:
                warning = f"\n\n⚠️ {category} at {pct:.0%} of budget ({currency} {spent:.2f} / {currency} {limit:.2f})"

        receipt = (
            f"✅ Saved #{expense_id}: *{pending['description']}* — "
            f"{currency} {pending['amount']:.2f} — {category}{warning}"
        )
        await query.edit_message_text(receipt, parse_mode="Markdown")

    # ── Date quick-set on pending expense ─────────────────────────────────────
    elif data.startswith("date_set:"):
        parts = data.split(":", 2)
        uid, new_date = parts[1], parts[2]
        pending = context.user_data.get(uid)
        if not pending:
            await query.edit_message_text("This expense card has expired.")
            return
        pending["date"] = new_date
        from bot.handlers.expense import _build_confirm_card
        text, keyboard = _build_confirm_card(pending, currency)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    # ── Custom date: prompt for text input ────────────────────────────────────
    elif data.startswith("date_custom:"):
        uid = data.split(":", 1)[1]
        pending = context.user_data.get(uid)
        if not pending:
            await query.edit_message_text("This expense card has expired.")
            return
        context.user_data["waiting_for_date_uid"] = uid
        context.user_data["date_prompt_msg_id"] = query.message.message_id
        context.user_data["date_prompt_chat_id"] = query.message.chat_id
        await query.edit_message_text(
            f"*Enter date for this expense:*\n"
            f"_{pending['description']} — {currency} {pending['amount']:.2f}_\n\n"
            f"Accepted formats: `YYYY-MM-DD`, `DD/MM/YYYY`, `today`, `yesterday`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"date_custom_cancel:{uid}")
            ]]),
        )

    # ── Custom date: cancelled ────────────────────────────────────────────────
    elif data.startswith("date_custom_cancel:"):
        uid = data.split(":", 1)[1]
        context.user_data.pop("waiting_for_date_uid", None)
        context.user_data.pop("date_prompt_msg_id", None)
        context.user_data.pop("date_prompt_chat_id", None)
        pending = context.user_data.get(uid)
        if not pending:
            await query.edit_message_text("This expense card has expired.")
            return
        from bot.handlers.expense import _build_confirm_card
        text, keyboard = _build_confirm_card(pending, currency)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    # ── Edit: select expense from list ────────────────────────────────────────
    elif data.startswith("edit_select:"):
        expense_id = int(data.split(":")[1])
        row = db.get_expense(expense_id)
        if not row:
            await query.edit_message_text("Expense not found.")
            return
        from bot.handlers.expense import _build_edit_card
        text, keyboard = _build_edit_card(row, currency)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    # ── Edit: choose field to edit ────────────────────────────────────────────
    elif data.startswith("edit_field:"):
        _, expense_id_str, field = data.split(":", 2)
        expense_id = int(expense_id_str)
        row = db.get_expense(expense_id)
        if not row:
            await query.edit_message_text("Expense not found.")
            return

        if field == "category":
            buttons = []
            btn_row = []
            for cat in CATEGORIES:
                label = f"{cat} ✓" if cat == row["category"] else cat
                btn_row.append(InlineKeyboardButton(label, callback_data=f"edit_cat:{expense_id}:{cat}"))
                if len(btn_row) == 2:
                    buttons.append(btn_row)
                    btn_row = []
            if btn_row:
                buttons.append(btn_row)
            buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"edit_cancel:{expense_id}")])
            await query.edit_message_text(
                f"Select new category for expense #{expense_id}:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        current_value = row[field] or "—"
        context.user_data["waiting_for_edit"] = {
            "expense_id": expense_id,
            "field": field,
            "prompt_msg_id": query.message.message_id,
            "prompt_chat_id": query.message.chat_id,
        }
        await query.edit_message_text(
            f"*Edit expense #{expense_id} — {field.title()}*\n"
            f"Current: _{current_value}_\n\n"
            f"Enter new {_EDIT_FIELD_LABELS.get(field, field)}:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"edit_cancel:{expense_id}")
            ]]),
        )

    # ── Edit: set category directly ───────────────────────────────────────────
    elif data.startswith("edit_cat:"):
        _, expense_id_str, category = data.split(":", 2)
        expense_id = int(expense_id_str)
        row = db.get_expense(expense_id)
        if not row:
            await query.edit_message_text("Expense not found.")
            return
        db.update_expense(expense_id, category=category)
        logger.info("[EDIT] id=%s category → %s", expense_id, category)
        row = db.get_expense(expense_id)
        from bot.handlers.expense import _build_edit_card
        text, keyboard = _build_edit_card(row, currency)
        await query.edit_message_text(
            f"✅ Category updated to *{category}*\n\n" + text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    # ── Edit: cancelled ───────────────────────────────────────────────────────
    elif data.startswith("edit_cancel:"):
        expense_id = int(data.split(":")[1])
        context.user_data.pop("waiting_for_edit", None)
        await query.edit_message_text(f"Edit of expense #{expense_id} cancelled.")

    # ── Delete: show last-5 list → select one ────────────────────────────────
    elif data.startswith("delete_select:"):
        expense_id = int(data.split(":")[1])
        row = db.get_expense(expense_id)
        if not row:
            await query.edit_message_text("Expense not found.")
            return

        note = f" ({row['note']})" if row['note'] else ""
        text = (
            f"Delete this expense?\n\n"
            f"#{row['id']} | {row['date']} | {row['description']}{note} | {currency} {row['amount']:.2f}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, delete", callback_data=f"delete_confirm:{expense_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"delete_cancel:{expense_id}"),
            ]
        ])
        await query.edit_message_text(text, reply_markup=keyboard)

    # ── Delete: confirmed ─────────────────────────────────────────────────────
    elif data.startswith("delete_confirm:"):
        expense_id = int(data.split(":")[1])
        row = db.get_expense(expense_id)
        if not row:
            await query.edit_message_text("Expense not found.")
            return
        db.delete_expense(expense_id)
        logger.info("[DELETE] id=%s | %s %.2f", expense_id, row["description"], row["amount"])
        await query.edit_message_text(f"🗑 Expense #{expense_id} deleted.")

    # ── Delete: cancelled ─────────────────────────────────────────────────────
    elif data.startswith("delete_cancel:"):
        await query.edit_message_text("Deletion cancelled.")
