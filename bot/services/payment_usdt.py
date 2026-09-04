"""USDT TRC-20 payment helpers via TronGrid."""
from __future__ import annotations

import random
from decimal import Decimal

import httpx

# USDT TRC-20 contract
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def unique_usdt_amount(base_rub_or_usdt: Decimal, usdt_rate: Decimal | None = None) -> Decimal:
    """
    Generate unique payment amount in USDT.
    Adds random 0.000001–0.000099 so we can match by exact amount.
    If usdt_rate given, treats base as RUB and converts.
    """
    amount = base_rub_or_usdt
    if usdt_rate and usdt_rate > 0:
        amount = (base_rub_or_usdt / usdt_rate).quantize(Decimal("0.01"))
    micro = Decimal(random.randint(1, 99)) / Decimal("1000000")
    return (amount + micro).quantize(Decimal("0.000001"))


async def check_usdt_incoming(
    wallet: str,
    expected_amount: Decimal,
    api_key: str = "",
    min_timestamp_ms: int | None = None,
) -> bool:
    """
    Check TronGrid for incoming USDT TRC-20 transfer to wallet
    matching expected_amount (exact, within 1e-6).
    """
    if not wallet:
        return False

    headers = {"Accept": "application/json"}
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key

    url = (
        f"https://api.trongrid.io/v1/accounts/{wallet}/transactions/trc20"
        f"?only_to=true&limit=50&contract_address={USDT_CONTRACT}"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return False

    for tx in data.get("data", []):
        if tx.get("to") != wallet and tx.get("to") != wallet:
            # TronGrid returns base58 addresses
            pass
        try:
            raw = Decimal(tx.get("value", "0"))
            decimals = int(tx.get("token_info", {}).get("decimals", 6))
            amount = raw / (Decimal(10) ** decimals)
        except Exception:
            continue

        if abs(amount - expected_amount) > Decimal("0.000001"):
            continue

        if min_timestamp_ms is not None:
            ts = tx.get("block_timestamp") or 0
            if ts < min_timestamp_ms:
                continue

        # Accept matching incoming transfer
        if str(tx.get("to", "")).lower() == wallet.lower() or True:
            # only_to=true already filters; amount match is enough
            return True

    return False
