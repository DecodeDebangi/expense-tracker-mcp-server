import pytest
import os
from dotenv import load_dotenv
from expense_tracker_mcp_server.server import (
    add_expense,
    list_expenses,
    summarize,
    update_expense,
    delete_expense,
    bulk_add_expenses,
    categories,
    validate_date,
    validate_amount,
    validate_currency,
    validate_user_id
)

load_dotenv()

TEST_USER_1 = "test_user_alice"
TEST_USER_2 = "test_user_bob"

def test_validations():
    assert validate_date("2026-10-03") == "2026-10-03"
    with pytest.raises(ValueError, match="Invalid date format"):
        validate_date("2026-13-45")

    assert validate_amount(50.254) == 50.25
    with pytest.raises(ValueError, match="strictly greater than 0"):
        validate_amount(-10)

    assert validate_currency("usd") == "USD"
    with pytest.raises(ValueError, match="Invalid currency code"):
        validate_currency("USDD")

    assert validate_user_id("user_123") == "user_123"
    with pytest.raises(ValueError, match="Invalid user_id"):
        validate_user_id("user!@#")

@pytest.mark.asyncio
async def test_add_and_list_expense_supabase():
    # Clean up previous test entries
    res_list_init = await list_expenses("2026-10-01", "2026-10-31", user_id=TEST_USER_1)
    if res_list_init["status"] == "success":
        for item in res_list_init.get("expenses", []):
            await delete_expense(item["id"], user_id=TEST_USER_1)

    # Add expense
    res_add = await add_expense(
        date="2026-10-01",
        amount=45.50,
        category="food",
        subcategory="groceries",
        note="Weekly shopping",
        currency="USD",
        user_id=TEST_USER_1
    )
    assert res_add["status"] == "success"
    assert "id" in res_add
    exp_id = res_add["id"]

    # List expense
    res_list = await list_expenses("2026-10-01", "2026-10-31", user_id=TEST_USER_1)
    assert res_list["status"] == "success"
    assert res_list["total_count"] >= 1
    expenses = res_list["expenses"]
    matching = [e for e in expenses if e["id"] == exp_id]
    assert len(matching) == 1
    assert float(matching[0]["amount"]) == 45.50

    # Clean up
    await delete_expense(exp_id, user_id=TEST_USER_1)

@pytest.mark.asyncio
async def test_summarize_and_bulk_supabase():
    # Clean up
    res_list_init = await list_expenses("2026-10-01", "2026-10-31", user_id=TEST_USER_2)
    if res_list_init["status"] == "success":
        for item in res_list_init.get("expenses", []):
            await delete_expense(item["id"], user_id=TEST_USER_2)

    bulk_data = [
        {"date": "2026-10-01", "amount": 100.0, "category": "food", "currency": "USD"},
        {"date": "2026-10-02", "amount": 50.0, "category": "food", "currency": "USD"},
        {"date": "2026-10-03", "amount": 2000.0, "category": "transport", "currency": "INR"}
    ]
    res_bulk = await bulk_add_expenses(bulk_data, user_id=TEST_USER_2)
    assert res_bulk["status"] == "success"
    assert res_bulk["count"] == 3

    res_sum = await summarize("2026-10-01", "2026-10-31", user_id=TEST_USER_2)
    assert res_sum["status"] == "success"
    assert res_sum["grand_totals"]["USD"] == 150.0
    assert res_sum["grand_totals"]["INR"] == 2000.0

    # Clean up
    res_list_after = await list_expenses("2026-10-01", "2026-10-31", user_id=TEST_USER_2)
    for item in res_list_after.get("expenses", []):
        await delete_expense(item["id"], user_id=TEST_USER_2)

def test_categories_resource():
    cat_str = categories()
    assert "food" in cat_str
    assert "groceries" in cat_str
