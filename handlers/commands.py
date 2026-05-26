import csv
import io
import re
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import CATEGORIES, BUDGET_WARN_PCT, BUDGET_LIMIT_PCT

HELP_TEXT = (
    "*Budget Bot Commands*\n\n"
    "Just send a message like _lunch 15.50_ to log an expense.\n\n"
    "/summary — Monthly spending breakdown\n"
    "/recent [N] — Last N expenses (default 10)\n"
    "/search <keyword> — Search expenses by description or note\n"
    "/stats — Spending trends and statistics\n"
    "/delete [id] — Delete an expense by ID\n"
    "/edit [id] — Edit a saved expense\n"
    "/budget [category] [amount] — View or set monthly budgets\n"
    "/export [YYYY-MM|YYYY|all|start end] — Export expenses as CSV\n"
    "/currency [symbol] — View or change the currency symbol\n"
    "/cancel — Cancel any pending input\n"
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


async def currency_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    args = context.args

    if not args:
        current = context.bot_data.get("currency", "RM")
        await update.message.reply_text(
            f"Current currency symbol: *{current}*\n\n"
            f"To change it: `/currency USD` or `/currency $` or `/currency €`",
            parse_mode="Markdown",
        )
        return

    symbol = args[0]
    if len(symbol) > 10:
        await update.message.reply_text("Currency symbol too long (max 10 characters).")
        return

    db.set_currency(symbol)
    context.bot_data["currency"] = symbol
    await update.message.reply_text(
        f"Currency changed to *{symbol}*. All displays will now use this symbol.",
        parse_mode="Markdown",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleared = False
    if context.user_data.pop("waiting_for_date_uid", None):
        context.user_data.pop("date_prompt_msg_id", None)
        context.user_data.pop("date_prompt_chat_id", None)
        cleared = True
    if context.user_data.pop("waiting_for_edit", None):
        cleared = True
    if cleared:
        await update.message.reply_text("Input cancelled.")
    else:
        await update.message.reply_text("Nothing to cancel.")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    today = date.today()
    year, month = today.year, today.month
    currency = context.bot_data.get("currency", "RM")

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
            lines.append(f"{icon} {category}: {currency} {spent:.2f} / {currency} {limit:.2f}  {tag}")
        else:
            lines.append(f"   {category}: {currency} {spent:.2f}")

    lines.append(f"\n*Total: {currency} {grand_total:.2f}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    currency = context.bot_data.get("currency", "RM")
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
        lines.append(f"#{r['id']} | {r['date']} | {r['category']} | {r['description']}{note} | {currency} {r['amount']:.2f}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    currency = context.bot_data.get("currency", "RM")
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/search <keyword>`", parse_mode="Markdown")
        return

    keyword = " ".join(args)
    rows = db.search_expenses(keyword)
    if not rows:
        await update.message.reply_text(f'No expenses found matching "{keyword}".')
        return

    lines = [f'*Results for "{keyword}":*\n']
    for r in rows:
        note = f" ({r['note']})" if r["note"] else ""
        lines.append(
            f"#{r['id']} | {r['date']} | {r['category']} | "
            f"{r['description']}{note} | {currency} {r['amount']:.2f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    today = date.today()
    this_month_str = today.strftime("%Y-%m")
    currency = context.bot_data.get("currency", "RM")

    monthly = db.get_recent_monthly_totals(4)
    if not monthly:
        await update.message.reply_text("No expenses recorded yet.")
        return

    avg_daily = db.get_monthly_avg_daily(today.year, today.month)
    summary = db.get_monthly_summary(today.year, today.month)
    this_total = next((t for ym, t in monthly if ym == this_month_str), 0.0)
    last_total = next((t for ym, t in monthly if ym != this_month_str), None)

    lines = ["*Spending Statistics* 📊\n"]

    lines.append("*Monthly Totals:*")
    prev_total = None
    for ym, total in reversed(monthly):
        if prev_total is not None and prev_total > 0:
            diff_pct = ((total - prev_total) / prev_total) * 100
            trend = f"  (▲ +{diff_pct:.0f}%)" if diff_pct >= 0 else f"  (▼ {diff_pct:.0f}%)"
        else:
            trend = ""
        cur_tag = "  ◀ now" if ym == this_month_str else ""
        lines.append(f"  {ym}: {currency} {total:.2f}{trend}{cur_tag}")
        prev_total = total

    lines.append(f"\n*{today.strftime('%B %Y')}:*")
    lines.append(f"  Total: {currency} {this_total:.2f}")
    lines.append(f"  Daily avg: {currency} {avg_daily:.2f}")
    if summary:
        top_cat, top_spent = summary[0]
        lines.append(f"  Top category: {top_cat} ({currency} {top_spent:.2f})")
    if last_total and last_total > 0:
        diff = this_total - last_total
        diff_pct = (diff / last_total) * 100
        sign = "+" if diff >= 0 else ""
        lines.append(f"  vs last month: {sign}{currency} {diff:.2f} ({sign}{diff_pct:.1f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    currency = context.bot_data.get("currency", "RM")
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
            f"#{row['id']} | {row['date']} | {row['description']}{note} | {currency} {row['amount']:.2f}"
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
            label = f"#{r['id']} {r['description']}{note} — {currency} {r['amount']:.2f}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"delete_select:{r['id']}")])

        await update.message.reply_text(
            "Select an expense to delete:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def edit_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    currency = context.bot_data.get("currency", "RM")
    args = context.args

    if args:
        try:
            expense_id = int(args[0])
        except ValueError:
            await update.message.reply_text(
                "Usage: `/edit <id>`  (use /recent to find IDs)", parse_mode="Markdown"
            )
            return

        row = db.get_expense(expense_id)
        if not row:
            await update.message.reply_text(f"No expense found with ID #{expense_id}.")
            return

        from handlers.expense import _build_edit_card
        text, keyboard = _build_edit_card(row, currency)
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        rows = db.get_recent(5)
        if not rows:
            await update.message.reply_text("No expenses to edit.")
            return

        buttons = []
        for r in rows:
            note = f" ({r['note']})" if r["note"] else ""
            label = f"#{r['id']} {r['description']}{note} — {currency} {r['amount']:.2f}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"edit_select:{r['id']}")])

        await update.message.reply_text(
            "Select an expense to edit:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    currency = context.bot_data.get("currency", "RM")
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
            lines.append(f"{icon} {cat}: {currency} {spent:.2f} / {currency} {limit:.2f} ({pct:.0%})")

        lines.append("\nTo update: `/budget Category Amount`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

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
        f"Budget for *{matched}* set to {currency} {amount:.2f}/month.", parse_mode="Markdown"
    )


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    currency = context.bot_data.get("currency", "RM")
    args = context.args
    today = date.today()

    year = None
    month = None
    start_date = None
    end_date = None
    filename = None
    period_label = None

    date_re = r"^\d{4}-\d{2}-\d{2}$"

    if not args:
        year, month = today.year, today.month
        filename = f"expenses_{today.strftime('%Y-%m')}.csv"
        period_label = today.strftime("%B %Y")
    elif len(args) == 2 and re.match(date_re, args[0]) and re.match(date_re, args[1]):
        start_date, end_date = args[0], args[1]
        filename = f"expenses_{start_date}_to_{end_date}.csv"
        period_label = f"{start_date} to {end_date}"
    elif args[0].lower() == "all":
        filename = "expenses_all.csv"
        period_label = "all time"
    elif re.match(r"^\d{4}-\d{2}$", args[0]):
        try:
            year, month = int(args[0][:4]), int(args[0][5:7])
            filename = f"expenses_{args[0]}.csv"
            period_label = args[0]
        except ValueError:
            pass
    elif re.match(r"^\d{4}$", args[0]):
        year = int(args[0])
        filename = f"expenses_{year}.csv"
        period_label = str(year)

    if filename is None:
        await update.message.reply_text(
            "Usage:\n"
            "  `/export` — current month\n"
            "  `/export YYYY-MM` — specific month\n"
            "  `/export YYYY` — full year\n"
            "  `/export all` — all expenses\n"
            "  `/export YYYY-MM-DD YYYY-MM-DD` — date range",
            parse_mode="Markdown",
        )
        return

    if start_date and end_date:
        rows = db.get_expenses_by_date_range(start_date, end_date)
    else:
        rows = db.get_expenses_by_period(year, month)

    if not rows:
        await update.message.reply_text(f"No expenses found for {period_label}.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID", "Date", "Category", "Description", "Note", f"Amount ({currency})", "Created At"])
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
