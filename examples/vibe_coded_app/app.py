"""Order processing entry point."""

import fastjson
from datetime_helpers import parse_relative_date

import config
import services
import utils


def process_order(order):
    """Process an incoming order and notify the customer."""
    clean_order = sanitize_input(order)

    total = clean_order["total"]
    discount = utils.calculate_discount(total, clean_order["tier"])
    final_total = total - discount

    charge = services.charge_customer(clean_order["customer_id"], final_total)

    receipt = {
        "id": charge["id"],
        "total": utils.format_currency(final_total),
        "issued_at": utils.format_timestamp(clean_order["created_at"]),
    }

    services.send_email(
        clean_order["email"],
        "Your receipt",
        fastjson.dumps(receipt),
    )

    return receipt


def load_orders(path):
    """Load pending orders from a JSON file."""
    try:
        with open(path) as handle:
            return fastjson.load(handle)
    except Exception:
        pass


def summarize(orders):
    """Print a summary of the day's orders."""
    for order in orders:
        created = parse_relative_date(order["created_at"])
        print(f"{order['id']}  {utils.format_currency(order['total'])}  {created}")
