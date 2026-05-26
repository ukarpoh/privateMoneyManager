import csv
import io
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import CATEGORIES, BUDGET_WARN_PCT, BUDGET_LIMIT_PCT

HELP_TEXT = (
    "*Budget Bot Commands*\n\n"
    "Just send a message like _lunch 15.50_ to log an expense.\n\n"
    "/summary — Monthly spending breakdown\n"
    "/recent [N] — Last N expenses (default 10)\n"
    "/delete [id] — Delete an expense by ID\n"
    "/budget [category] [amount] — View or set monthly budgets\n"
    "/export [YYYY-MM|YYYY|all] — Export expenses as CSV\n"
    "/help — Show this message"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I'm your *Budget Bot* 💰\n\n"
        "Send me any expense in plain English and I'll track it for you.\n\n"
        + HELP_TEXT,
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    today = date.today()
    year, month = today.year, today.month

    monthly = db.get_monthly_summary(year, month)
    budgets = db.get_all_budgets()
    grand_total = db.get_monthly_total(year, month)

    if not monthly:
        await update.message.reply_text(
            f"No expenses recorded for {today.strftime('%B %Y')} yet."
        )
        return

    lines = [f"*{today.strftime('%B %Y')} Summary*\n"]
    for category, spent in monthly:
        limit = budgets.get(category)
        if limit and limit > 0:
            pct = spent / limit
            if pct >= BUDGET_LIMIT_PCT:
                icon = "🚨"
                tag = f"OVER BUDGET ({pct:.0%})"
            elif pct >= BUDGET_WARN_PCT:
                icon = "⚠️"
                tag = f"Near limit ({pct:.0%})"
            else:
                icon = "  "
                tag = f"{pct:.0%}"
            lines.append(f"{icon} {category}: RM {spent:.2f} / RM {limit:.2f}  {tag}")
        else:
            lines.append(f"   {category}: RM {spent:.2f}")

    lines.append(f"\n*Total: RM {grand_total:.2f}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    args = context.args
    try:
        limit = min(int(args[0]), 50) if args else 10
    except (ValueError, IndexError):
        limit = 10

    rows = db.get_recent(limit)
    if not rows:
        await update.message.reply_text("No expenses recorded yet.")
        return

    lines = [f"*Last {len(rows)} expenses:*\n"]
    for r in rows:
        note = f" ({r['note']})" if r['note'] else ""
        lines.append(f"#{r['id']} | {r['date']} | {r['category']} | {r['description']}{note} | RM {r['amount']:.2f}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    args = context.args

    if args:
        try:
            expense_id = int(args[0])
        except ValueError:
            await update.message.reply_text("Usage: /delete <id>  (use /recent to find IDs)")
            return

        row = db.get_expense(expense_id)
        if not row:
            await update.message.reply_text(f"No expense found with ID #{expense_id}.")
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
        await update.message.reply_text(text, reply_markup=keyboard)
    else:
        rows = db.get_recent(5)
        if not rows:
            await update.message.reply_text("No expenses to delete.")
            return

        buttons = []
        for r in rows:
            note = f" ({r['note']})" if r['note'] else ""
            label = f"#{r['id']} {r['description']}{note} — RM {r['amount']:.2f}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"delete_select:{r['id']}")])

        await update.message.reply_text(
            "Select an expense to delete:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    args = context.args
    today = date.today()

    if not args:
        budgets = db.get_all_budgets()
        if not budgets:
            await update.message.reply_text(
                "*No budgets set yet.*\n\n"
                "To set one: `/budget Food & Drinks 500`",
                parse_mode="Markdown",
            )
            return

        lines = ["*Monthly Budgets:*\n"]
        for cat, limit in budgets.items():
            spent = db.get_category_monthly_total(cat, today.year, today.month)
            pct = spent / limit if limit > 0 else 0
            if pct >= BUDGET_LIMIT_PCT:
                icon = "🚨"
            elif pct >= BUDGET_WARN_PCT:
                icon = "⚠️"
            else:
                icon = "  "
            lines.append(f"{icon} {cat}: RM {spent:.2f} / RM {limit:.2f} ({pct:.0%})")

        lines.append("\nTo update: `/budget Category Amount`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Parse: /budget <category> <amount>
    # Category may have spaces, so amount is always the last arg
    try:
        amount = float(args[-1])
    except ValueError:
        await update.message.reply_text(
            "Usage: `/budget Food & Drinks 500`", parse_mode="Markdown"
        )
        return

    category_input = " ".join(args[:-1]).strip()
    matched = next(
        (c for c in CATEGORIES if c.lower() == category_input.lower()), None
    )
    if not matched:
        cats = "\n".join(f"• {c}" for c in CATEGORIES)
        await update.message.reply_text(
            f"Unknown category: *{category_input}*\n\nAvailable:\n{cats}",
            parse_mode="Markdown",
        )
        return

    db.set_budget(matched, amount)
    await update.message.reply_text(
        f"Budget for *{matched}* set to RM {amount:.2f}/month.", parse_mode="Markdown"
    )


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    args = context.args

    year = None
    month = None
    today = date.today()

    if not args or args[0].lower() == "all":
        filename = "expenses_all.csv"
        period_label = "all time"
    elif len(args[0]) == 7 and args[0][4] == "-":
        try:
            year, month = int(args[0][:4]), int(args[0][5:7])
            filename = f"expenses_{args[0]}.csv"
            period_label = args[0]
        except ValueError:
            await update.message.reply_text(
                "Usage: `/export`, `/export YYYY-MM`, `/export YYYY`, `/export all`",
                parse_mode="Markdown",
            )
            return
    elif len(args[0]) == 4:
        try:
            year = int(args[0])
            filename = f"expenses_{year}.csv"
            period_label = str(year)
        except ValueError:
            await update.message.reply_text(
                "Usage: `/export`, `/export YYYY-MM`, `/export YYYY`, `/export all`",
                parse_mode="Markdown",
            )
            return
    else:
        await update.message.reply_text(
            "Usage: `/export`, `/export YYYY-MM`, `/export YYYY`, `/export all`",
            parse_mode="Markdown",
        )
        return

    # Default (no args) → current month
    if not args:
        year, month = today.year, today.month
        filename = f"expenses_{today.strftime('%Y-%m')}.csv"
        period_label = today.strftime("%B %Y")

    rows = db.get_expenses_by_period(year, month)

    if not rows:
        await update.message.reply_text(f"No expenses found for {period_label}.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID", "Date", "Category", "Description", "Note", "Amount (RM)", "Created At"])
    for r in rows:
        writer.writerow([
            r["id"],
            r["date"],
            r["category"],
            r["description"],
            r["note"] or "",
            f"{r['amount']:.2f}",
            r["created_at"],
        ])

    buffer.seek(0)
    await update.message.reply_document(
        document=io.BytesIO(buffer.getvalue().encode("utf-8")),
        filename=filename,
        caption=f"Exported {len(rows)} expense(s) for {period_label}.",
    )
