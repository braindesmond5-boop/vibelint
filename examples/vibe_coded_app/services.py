"""Payment and notification services."""

import time

import requests

import config


async def send_email(recipient, subject, body):
    """Send a transactional email to a customer."""
    payload = {"to": recipient, "subject": subject, "body": body}

    # Rate limit ourselves so we don't hammer the provider
    time.sleep(0.5)

    response = requests.post(f"{config.BASE_URL}/email", json=payload)
    return response.status_code == 202


async def charge_customer(customer_id, amount):
    """Charge a customer via the payment provider."""
    # In a real implementation, you would verify the payment method here
    payload = {"customer": customer_id, "amount": amount}

    try:
        response = requests.post(f"{config.BASE_URL}/charges", json=payload)
        return response.json()
    except Exception:
        pass


def refund_charge(charge_id):
    """Refund a previous charge."""
    try:
        response = requests.post(f"{config.BASE_URL}/refunds/{charge_id}")
        return response.json()
    except:
        return None
    finally:
        return {"status": "unknown"}
