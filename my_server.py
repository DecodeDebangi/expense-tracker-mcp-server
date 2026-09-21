from fastmcp import FastMCP
import os
import aiosqlite
import json

import tempfile

def get_db_path() -> str:
    if "DB_PATH" in os.environ:
        return os.environ["DB_PATH"]
    
    local_path = os.path.join(os.path.dirname(__file__), "expenses.db")
    try:
        test_path = os.path.join(os.path.dirname(__file__), ".write_test")
        with open(test_path, "w") as f:
            f.write("test")
        os.remove(test_path)
        return local_path
    except (OSError, PermissionError):
        return os.path.join(tempfile.gettempdir(), "expenses.db")

DB_PATH = get_db_path()
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

print(f"Database path: {DB_PATH}")

mcp = FastMCP("ExpenseTracker")

def init_db() -> None:  # Keep as sync for initialization
    try:
        import sqlite3
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as c:
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            c.execute("""
                CREATE TABLE IF NOT EXISTS expenses(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
            """)
            print(f"Database initialized successfully at {DB_PATH}")
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

# Initialize database synchronously at module load
init_db()


@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = ""
) -> dict:
    """Add a new expense entry to the database.

    Args:
        date: Date of the expense in YYYY-MM-DD format.
        amount: Numerical cost amount.
        category: Category of the expense (e.g. Food & Dining, Transportation).
        subcategory: Optional subcategory description.
        note: Optional extra notes.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
                (date, amount, category, subcategory, note)
            )
            expense_id = cur.lastrowid
            await c.commit()
            return {"status": "success", "id": expense_id, "message": "Expense added successfully"}
    except Exception as e:
        if "readonly" in str(e).lower():
            return {"status": "error", "message": "Database is in read-only mode. Check file permissions."}
        return {"status": "error", "message": f"Database error: {str(e)}"}

@mcp.tool()
async def list_expenses(start_date: str, end_date: str) -> list[dict] | dict:
    """List expense entries within an inclusive date range (YYYY-MM-DD).

    Args:
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).
    """
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                """
                SELECT id, date, amount, category, subcategory, note
                FROM expenses
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC, id DESC
                """,
                (start_date, end_date)
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": f"Error listing expenses: {str(e)}"}

@mcp.tool()
async def summarize(start_date: str, end_date: str, category: str | None = None) -> list[dict] | dict:
    """Summarize expenses by category within an inclusive date range.

    Args:
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).
        category: Optional category filter.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            query = """
                SELECT category, SUM(amount) AS total_amount, COUNT(*) as count
                FROM expenses
                WHERE date BETWEEN ? AND ?
            """
            params: list[str] = [start_date, end_date]

            if category:
                query += " AND category = ?"
                params.append(category)

            query += " GROUP BY category ORDER BY total_amount DESC"

            cur = await c.execute(query, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": f"Error summarizing expenses: {str(e)}"}

@mcp.tool()
async def delete_expense(expense_id: int) -> dict:
    """Delete an expense entry from the database by its ID.

    Args:
        expense_id: Unique integer ID of the expense to delete.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            await c.commit()
            if cur.rowcount == 0:
                return {"status": "error", "message": f"No expense found with id {expense_id}"}
            return {"status": "success", "message": f"Expense {expense_id} deleted successfully"}
    except Exception as e:
        return {"status": "error", "message": f"Error deleting expense: {str(e)}"}

@mcp.tool()
async def update_expense(
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None
) -> dict:
    """Update one or more fields of an existing expense entry.

    Args:
        expense_id: ID of the expense to update.
        date: Optional new date in YYYY-MM-DD format.
        amount: Optional new cost amount.
        category: Optional new category string.
        subcategory: Optional new subcategory string.
        note: Optional new note string.
    """
    fields = []
    params = []

    if date is not None:
        fields.append("date = ?")
        params.append(date)
    if amount is not None:
        fields.append("amount = ?")
        params.append(amount)
    if category is not None:
        fields.append("category = ?")
        params.append(category)
    if subcategory is not None:
        fields.append("subcategory = ?")
        params.append(subcategory)
    if note is not None:
        fields.append("note = ?")
        params.append(note)

    if not fields:
        return {"status": "error", "message": "No fields provided to update"}

    params.append(expense_id)
    query = f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?"

    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(query, params)
            await c.commit()
            if cur.rowcount == 0:
                return {"status": "error", "message": f"No expense found with id {expense_id}"}
            return {"status": "success", "message": f"Expense {expense_id} updated successfully"}
    except Exception as e:
        return {"status": "error", "message": f"Error updating expense: {str(e)}"}

@mcp.tool()
async def bulk_add_expenses(expenses: list[dict]) -> dict:
    """Bulk add multiple expense entries to the database in a single transaction.

    Args:
        expenses: A list of dict objects, each containing 'date', 'amount', 'category', and optionally 'subcategory' and 'note'.
    """
    if not expenses:
        return {"status": "error", "message": "Expenses list cannot be empty"}

    records = []
    for item in expenses:
        if "date" not in item or "amount" not in item or "category" not in item:
            return {
                "status": "error",
                "message": f"Each expense item must contain 'date', 'amount', and 'category'. Missing in: {item}"
            }
        records.append((
            str(item["date"]),
            float(item["amount"]),
            str(item["category"]),
            str(item.get("subcategory", "")),
            str(item.get("note", ""))
        ))

    try:
        async with aiosqlite.connect(DB_PATH) as c:
            await c.executemany(
                "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
                records
            )
            await c.commit()
            return {"status": "success", "count": len(records), "message": f"Successfully added {len(records)} expenses"}
    except Exception as e:
        return {"status": "error", "message": f"Error bulk inserting expenses: {str(e)}"}


@mcp.resource("expense:///categories", mime_type="application/json")
def categories() -> str:
    """Returns available expense categories as JSON string."""
    try:
        default_categories = {
            "categories": [
                "Food & Dining",
                "Transportation",
                "Shopping",
                "Entertainment",
                "Bills & Utilities",
                "Healthcare",
                "Travel",
                "Education",
                "Business",
                "Other"
            ]
        }

        try:
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return json.dumps(default_categories, indent=2)
    except Exception as e:
        return f'{{"error": "Could not load categories: {str(e)}"}}'

# Start the server
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)