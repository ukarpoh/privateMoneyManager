import sqlite3
from datetime import date

from bot.config import CURRENCY_SYMBOL, DB_PATH


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount      REAL    NOT NULL,
                    description TEXT    NOT NULL,
                    note        TEXT,
                    category    TEXT    NOT NULL,
                    date        TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS budgets (
                    category      TEXT PRIMARY KEY,
                    monthly_limit REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_expenses_date
                    ON expenses(date);
                CREATE INDEX IF NOT EXISTS idx_expenses_category
                    ON expenses(category);
            """)

    # ── Expenses ──────────────────────────────────────────────────────────────

    def add_expense(
        self, amount: float, description: str, note: str, category: str, expense_date: str
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO expenses (amount, description, note, category, date) "
                "VALUES (?, ?, ?, ?, ?)",
                (amount, description, note or "", category, expense_date),
            )
            return cur.lastrowid

    def get_expense(self, expense_id: int) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM expenses WHERE id = ?", (expense_id,)
            ).fetchone()

    def get_recent(self, limit: int = 10) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM expenses ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def delete_expense(self, expense_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            return cur.rowcount > 0

    def update_expense(self, expense_id: int, **fields) -> bool:
        allowed = {"amount", "description", "note", "category", "date"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [expense_id]
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE expenses SET {set_clause} WHERE id = ?", values
            )
            return cur.rowcount > 0

    def search_expenses(self, keyword: str, limit: int = 20) -> list[sqlite3.Row]:
        pattern = f"%{keyword}%"
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM expenses "
                "WHERE description LIKE ? OR note LIKE ? "
                "ORDER BY date DESC, id DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()

    def get_expenses_by_period(
        self, year: int | None = None, month: int | None = None
    ) -> list[sqlite3.Row]:
        with self._conn() as conn:
            if year and month:
                prefix = f"{year}-{month:02d}"
                return conn.execute(
                    "SELECT * FROM expenses WHERE date LIKE ? ORDER BY date ASC, id ASC",
                    (f"{prefix}%",),
                ).fetchall()
            if year:
                return conn.execute(
                    "SELECT * FROM expenses WHERE date LIKE ? ORDER BY date ASC, id ASC",
                    (f"{year}%",),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM expenses ORDER BY date ASC, id ASC"
            ).fetchall()

    def get_expenses_by_date_range(
        self, start_date: str, end_date: str
    ) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM expenses WHERE date BETWEEN ? AND ? "
                "ORDER BY date ASC, id ASC",
                (start_date, end_date),
            ).fetchall()

    # ── Summaries ─────────────────────────────────────────────────────────────

    def get_monthly_summary(self, year: int, month: int) -> list[tuple]:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT category, SUM(amount) as total "
                "FROM expenses WHERE date LIKE ? "
                "GROUP BY category ORDER BY total DESC",
                (f"{prefix}%",),
            ).fetchall()
            return [(r["category"], r["total"]) for r in rows]

    def get_monthly_total(self, year: int, month: int) -> float:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT SUM(amount) as total FROM expenses WHERE date LIKE ?",
                (f"{prefix}%",),
            ).fetchone()
            return row["total"] or 0.0

    def get_category_monthly_total(self, category: str, year: int, month: int) -> float:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT SUM(amount) as total FROM expenses "
                "WHERE category = ? AND date LIKE ?",
                (category, f"{prefix}%"),
            ).fetchone()
            return row["total"] or 0.0

    def get_recent_monthly_totals(self, months: int = 4) -> list[tuple]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT strftime('%Y-%m', date) as ym, SUM(amount) as total "
                "FROM expenses GROUP BY ym ORDER BY ym DESC LIMIT ?",
                (months,),
            ).fetchall()
            return [(r["ym"], r["total"]) for r in rows]

    def get_monthly_avg_daily(self, year: int, month: int) -> float:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT date) as days, SUM(amount) as total "
                "FROM expenses WHERE date LIKE ?",
                (f"{prefix}%",),
            ).fetchone()
            days = row["days"] or 1
            total = row["total"] or 0.0
            return total / days

    # ── Budgets ───────────────────────────────────────────────────────────────

    def set_budget(self, category: str, monthly_limit: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO budgets (category, monthly_limit) VALUES (?, ?)",
                (category, monthly_limit),
            )

    def get_budget(self, category: str) -> float | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT monthly_limit FROM budgets WHERE category = ?", (category,)
            ).fetchone()
            return row["monthly_limit"] if row else None

    def get_all_budgets(self) -> dict[str, float]:
        with self._conn() as conn:
            rows = conn.execute("SELECT category, monthly_limit FROM budgets").fetchall()
            return {r["category"]: r["monthly_limit"] for r in rows}

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_currency(self) -> str:
        return self.get_setting("currency", CURRENCY_SYMBOL)

    def set_currency(self, symbol: str) -> None:
        self.set_setting("currency", symbol)
