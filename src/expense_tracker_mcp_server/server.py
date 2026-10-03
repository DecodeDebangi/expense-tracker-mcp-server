import os
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentHeaders, Depends

# Load environment variables from .env file
load_dotenv()

mcp = FastMCP("ExpenseTracker")

# Path to categories.json inside package
PACKAGE_DIR = Path(__file__).parent.resolve()
CATEGORIES_PATH = PACKAGE_DIR / "categories.json"

USER_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
CURRENCY_REGEX = re.compile(r"^[A-Z]{3}$")

def get_supabase_client() -> Client:
    """Returns an initialized Supabase client."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise ValueError(
            "Supabase database connection is not configured on the server. "
            "Please set SUPABASE_URL and SUPABASE_KEY environment variables in your deployment settings."
        )
    return create_client(url, key)

def get_categories_data() -> Dict[str, List[str]]:
    """Loads categories mapping from package categories.json."""
    if CATEGORIES_PATH.exists():
        try:
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "food": ["groceries", "dining_out", "coffee_tea", "delivery_fees", "other"],
        "transport": ["fuel", "public_transport", "cab_ride_hailing", "parking", "other"],
        "housing": ["rent", "maintenance_hoa", "repairs_service", "other"],
        "utilities": ["electricity", "water", "gas", "internet_broadband", "mobile_phone", "other"],
        "health": ["medicines", "doctor_consultation", "insurance_health", "fitness_gym", "other"],
        "entertainment": ["movies_events", "streaming_subscriptions", "games_apps", "other"],
        "shopping": ["clothing", "electronics_gadgets", "other"],
        "misc": ["uncategorized", "other"]
    }

def get_current_user_id(headers: dict = CurrentHeaders()) -> str:
    """Extracts user identity from HTTP headers ('x-user-id', 'x-consumer-username') or defaults to 'default_user'."""
    user_id = headers.get("x-user-id") or headers.get("x-consumer-username") or "default_user"
    return user_id.strip()

def validate_user_id(user_id: str) -> str:
    """Validates user_id format."""
    user_id = user_id.strip()
    if not USER_ID_REGEX.match(user_id):
        raise ValueError(
            f"Invalid user_id '{user_id}'. Must be 1-64 alphanumeric characters, underscores, or hyphens."
        )
    return user_id.lower()

def resolve_user_id(param_user_id: Optional[str], header_user_id: str) -> str:
    """Resolves user_id from explicit tool argument or HTTP header fallback."""
    raw_user = (param_user_id or "").strip() or header_user_id
    return validate_user_id(raw_user)

def validate_date(date_str: str) -> str:
    """Validates that date is in YYYY-MM-DD format."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format '{date_str}'. Must be in YYYY-MM-DD format.")

def validate_amount(amount: float) -> float:
    """Validates that amount is positive and rounds to 2 decimal places."""
    if amount <= 0:
        raise ValueError(f"Expense amount must be strictly greater than 0. Received: {amount}")
    return round(float(amount), 2)

def validate_currency(currency_str: str) -> str:
    """Validates 3-letter uppercase ISO currency code."""
    c = currency_str.strip().upper()
    if not CURRENCY_REGEX.match(c):
        raise ValueError(f"Invalid currency code '{currency_str}'. Must be a 3-letter ISO code like USD, EUR, INR.")
    return c

def validate_category(category: str, subcategory: str = "") -> tuple[str, str]:
    """Validates category and subcategory strings."""
    cat = category.strip()
    subcat = subcategory.strip()
    if not cat:
        raise ValueError("Category cannot be empty.")
    return cat, subcat

@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
    currency: str = "USD",
    user_id: Optional[str] = None,
    header_user_id: str = Depends(get_current_user_id)
) -> dict:
    """Add a new expense entry to Supabase database.

    Args:
        date: Date of the expense in YYYY-MM-DD format.
        amount: Numerical cost amount (> 0).
        category: Category of the expense (e.g. food, transport, housing).
        subcategory: Optional subcategory description.
        note: Optional extra notes.
        currency: 3-letter currency code (default: 'USD').
        user_id: Optional user identifier / username (e.g. 'debangi').
    """
    try:
        valid_user = resolve_user_id(user_id, header_user_id)
        valid_date = validate_date(date)
        valid_amount = validate_amount(amount)
        valid_cat, valid_subcat = validate_category(category, subcategory)
        valid_currency = validate_currency(currency)

        client = get_supabase_client()
        record = {
            "user_id": valid_user,
            "date": valid_date,
            "amount": valid_amount,
            "currency": valid_currency,
            "category": valid_cat,
            "subcategory": valid_subcat,
            "note": note.strip()
        }

        res = client.table("expenses").insert(record).execute()
        if res.data and len(res.data) > 0:
            inserted = res.data[0]
            return {
                "status": "success",
                "id": inserted.get("id"),
                "expense": inserted,
                "message": f"Expense added successfully for user '{valid_user}'"
            }
        return {"status": "error", "message": "Failed to insert expense entry into Supabase"}
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Supabase error: {str(e)}"}

@mcp.tool()
async def list_expenses(
    start_date: str,
    end_date: str,
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_id: Optional[str] = None,
    header_user_id: str = Depends(get_current_user_id)
) -> dict:
    """List expense entries from Supabase within an inclusive date range (YYYY-MM-DD) with pagination.

    Args:
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).
        category: Optional category filter.
        limit: Maximum number of records to return (1-500, default: 100).
        offset: Offset for pagination (default: 0).
        user_id: Optional user identifier / username (e.g. 'debangi').
    """
    try:
        valid_user = resolve_user_id(user_id, header_user_id)
        v_start = validate_date(start_date)
        v_end = validate_date(end_date)
        if v_start > v_end:
            return {"status": "error", "message": f"start_date '{v_start}' cannot be after end_date '{v_end}'."}

        limit = max(1, min(500, limit))
        offset = max(0, offset)

        client = get_supabase_client()
        query = (
            client.table("expenses")
            .select("*", count="exact")
            .eq("user_id", valid_user)
            .gte("date", v_start)
            .lte("date", v_end)
        )

        if category and category.strip():
            query = query.ilike("category", category.strip())

        query = query.order("date", desc=True).order("id", desc=True).range(offset, offset + limit - 1)
        res = query.execute()

        return {
            "status": "success",
            "user_id": valid_user,
            "total_count": res.count if res.count is not None else len(res.data),
            "limit": limit,
            "offset": offset,
            "expenses": res.data or []
        }
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Error listing expenses: {str(e)}"}

@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: Optional[str] = None,
    currency: Optional[str] = None,
    user_id: Optional[str] = None,
    header_user_id: str = Depends(get_current_user_id)
) -> dict:
    """Summarize total expenses grouped by category and currency within an inclusive date range in Supabase.

    Args:
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).
        category: Optional category filter.
        currency: Optional currency filter (e.g. 'USD').
        user_id: Optional user identifier / username (e.g. 'debangi').
    """
    try:
        valid_user = resolve_user_id(user_id, header_user_id)
        v_start = validate_date(start_date)
        v_end = validate_date(end_date)
        if v_start > v_end:
            return {"status": "error", "message": f"start_date '{v_start}' cannot be after end_date '{v_end}'."}

        client = get_supabase_client()
        query = (
            client.table("expenses")
            .select("category, currency, amount")
            .eq("user_id", valid_user)
            .gte("date", v_start)
            .lte("date", v_end)
        )

        if category and category.strip():
            query = query.ilike("category", category.strip())

        if currency and currency.strip():
            query = query.eq("currency", validate_currency(currency))

        res = query.execute()
        rows = res.data or []

        # Aggregation logic
        group_map: Dict[tuple, Dict[str, Any]] = {}
        for r in rows:
            cat = r["category"]
            curr = r["currency"]
            amt = float(r["amount"])
            key = (cat, curr)
            if key not in group_map:
                group_map[key] = {"category": cat, "currency": curr, "total_amount": 0.0, "count": 0}
            group_map[key]["total_amount"] += amt
            group_map[key]["count"] += 1

        summary_items = []
        grand_totals: Dict[str, float] = {}
        for (cat, curr), data in group_map.items():
            tot = round(data["total_amount"], 2)
            summary_items.append({
                "category": cat,
                "currency": curr,
                "total_amount": tot,
                "count": data["count"]
            })
            grand_totals[curr] = round(grand_totals.get(curr, 0.0) + tot, 2)

        summary_items.sort(key=lambda x: x["total_amount"], reverse=True)

        return {
            "status": "success",
            "user_id": valid_user,
            "start_date": v_start,
            "end_date": v_end,
            "summary": summary_items,
            "grand_totals": grand_totals
        }
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Error summarizing expenses: {str(e)}"}

@mcp.tool()
async def update_expense(
    expense_id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    note: Optional[str] = None,
    currency: Optional[str] = None,
    user_id: Optional[str] = None,
    header_user_id: str = Depends(get_current_user_id)
) -> dict:
    """Update one or more fields of an existing expense entry in Supabase.

    Args:
        expense_id: Unique integer ID of the expense to update.
        date: Optional new date (YYYY-MM-DD).
        amount: Optional new numerical cost amount (> 0).
        category: Optional new category string.
        subcategory: Optional new subcategory string.
        note: Optional new note string.
        currency: Optional new 3-letter currency code (e.g. 'USD').
        user_id: Optional user identifier / username (e.g. 'debangi').
    """
    try:
        valid_user = resolve_user_id(user_id, header_user_id)
        updates: Dict[str, Any] = {}

        if date is not None:
            updates["date"] = validate_date(date)
        if amount is not None:
            updates["amount"] = validate_amount(amount)
        if category is not None:
            valid_cat, _ = validate_category(category, subcategory or "")
            updates["category"] = valid_cat
        if subcategory is not None:
            updates["subcategory"] = subcategory.strip()
        if note is not None:
            updates["note"] = note.strip()
        if currency is not None:
            updates["currency"] = validate_currency(currency)

        if not updates:
            return {"status": "error", "message": "No fields provided to update"}

        client = get_supabase_client()
        res = (
            client.table("expenses")
            .update(updates)
            .eq("id", expense_id)
            .eq("user_id", valid_user)
            .execute()
        )

        if res.data and len(res.data) > 0:
            return {"status": "success", "message": f"Expense {expense_id} updated successfully"}
        return {"status": "error", "message": f"No expense found with id {expense_id} for user '{valid_user}'"}
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Error updating expense: {str(e)}"}

@mcp.tool()
async def delete_expense(
    expense_id: int,
    user_id: Optional[str] = None,
    header_user_id: str = Depends(get_current_user_id)
) -> dict:
    """Delete an expense entry from Supabase by its ID.

    Args:
        expense_id: Unique integer ID of the expense to delete.
        user_id: Optional user identifier / username (e.g. 'debangi').
    """
    try:
        valid_user = resolve_user_id(user_id, header_user_id)
        client = get_supabase_client()
        res = (
            client.table("expenses")
            .delete()
            .eq("id", expense_id)
            .eq("user_id", valid_user)
            .execute()
        )

        if res.data and len(res.data) > 0:
            return {"status": "success", "message": f"Expense {expense_id} deleted successfully"}
        return {"status": "error", "message": f"No expense found with id {expense_id} for user '{valid_user}'"}
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Error deleting expense: {str(e)}"}

@mcp.tool()
async def bulk_add_expenses(
    expenses: List[dict],
    user_id: Optional[str] = None,
    header_user_id: str = Depends(get_current_user_id)
) -> dict:
    """Bulk add multiple expense entries to Supabase in a single request.

    Args:
        expenses: A list of dict objects, each containing 'date', 'amount', 'category', and optionally 'subcategory', 'note', and 'currency'.
        user_id: Optional user identifier / username (e.g. 'debangi').
    """
    if not expenses:
        return {"status": "error", "message": "Expenses list cannot be empty"}

    records = []
    try:
        valid_user = resolve_user_id(user_id, header_user_id)
        for idx, item in enumerate(expenses):
            if "date" not in item or "amount" not in item or "category" not in item:
                return {
                    "status": "error",
                    "message": f"Item at index {idx} missing required fields ('date', 'amount', 'category'). Item: {item}"
                }
            
            v_date = validate_date(str(item["date"]))
            v_amount = validate_amount(float(item["amount"]))
            v_cat, v_subcat = validate_category(str(item["category"]), str(item.get("subcategory", "")))
            v_currency = validate_currency(str(item.get("currency", "USD")))
            v_note = str(item.get("note", "")).strip()

            records.append({
                "user_id": valid_user,
                "date": v_date,
                "amount": v_amount,
                "currency": v_currency,
                "category": v_cat,
                "subcategory": v_subcat,
                "note": v_note
            })

        client = get_supabase_client()
        res = client.table("expenses").insert(records).execute()
        count = len(res.data) if res.data else len(records)
        return {"status": "success", "count": count, "message": f"Successfully added {count} expenses for user '{valid_user}'"}
    except ValueError as ve:
        return {"status": "error", "message": str(ve)}
    except Exception as e:
        return {"status": "error", "message": f"Error bulk inserting expenses: {str(e)}"}

@mcp.resource("expense:///categories", mime_type="application/json")
def categories() -> str:
    """Returns available expense categories as JSON string."""
    try:
        cats = get_categories_data()
        return json.dumps(cats, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Could not load categories: {str(e)}"})

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
