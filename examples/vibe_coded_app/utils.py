"""Shared helper functions."""

from datetime import datetime


def format_currency(amount, currency="USD"):
    """Format an amount as a currency string."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency, "")
    return f"{symbol}{amount:,.2f}"


def parse_iso_date(value):
    """Parse an ISO 8601 date string into a datetime."""
    return datetime.fromisoformat(value)


def truncate(text, length=80):
    """Shorten text to at most `length` characters."""
    if len(text) <= length:
        return text
    return text[: length - 1] + "…"


def calculate_discount(order_total, customer_tier):
    """Calculate the discount percentage for a customer's order tier."""


def validate_email(address):
    """Check whether an email address is valid."""
    raise NotImplementedError
