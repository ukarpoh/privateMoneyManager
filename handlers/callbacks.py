import logging
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import BUDGET_WARN_PCT, BUDGET_LIMIT_PCT

logger = logging.getLogger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    db = context.bot_data["db"]
    today = date.today()

    # ── Category selection: save expense ──────────────────────────────────────
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
            "[SAVE] id=%s | %s | RM %.2f | %s | date=%s | note=%r",
            expense_id, pending["description"], pending["amount"],
            category, pending["date"], pending["note"],
        )

        del context.user_data[uid]

        # Proactive budget warning
        warning = ""
        spent = db.get_category_monthly_total(category, today.year, today.month)
        limit = db.get_budget(category)
        if limit and limit > 0:
            pct = spent / limit
            if pct >= BUDGET_LIMIT_PCT:
                warning = f"\n\n🚨 *Over budget!* {category}: RM {spent:.2f} / RM {limit:.2f}"
            elif pct >= BUDGET_WARN_PCT:
                warning = f"\n\n⚠️ {category} at {pct:.0%} of budget (RM {spent:.2f} / RM {limit:.2f})"

        receipt = (
            f"✅ Saved #{expense_id}: *{pending['description']}* — "
            f"RM {pending['amount']:.2f} — {category}{warning}"
        )
        await query.edit_message_text(receipt, parse_mode="Markdown")

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
            f"#{row['id']} | {row['date']} | {row['description']}{note} | RM {row['amount']:.2f}"
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
        logger.info("[DELETE] id=%s | %s RM %.2f", expense_id, row["description"], row["amount"])
        await query.edit_message_text(f"🗑 Expense #{expense_id} deleted.")

    # ── Delete: cancelled ─────────────────────────────────────────────────────
    elif data.startswith("delete_cancel:"):
        await query.edit_message_text("Deletion cancelled.")
