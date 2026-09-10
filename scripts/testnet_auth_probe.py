#!/usr/bin/env python3

import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import json

base = os.environ.get(
    "BINANCE_TESTNET_URL",
    "https://testnet.binancefuture.com"
).rstrip("/")

key = os.environ.get(
    "BINANCE_TESTNET_API_KEY",
    ""
)

secret = os.environ.get(
    "BINANCE_TESTNET_SECRET",
    ""
)

if not key or not secret:
    print(
        "TESTNET_AUTH=NOT_CONFIGURED"
    )
    raise SystemExit(2)


def get(path, params=None, signed=False):

    params = params or {}

    if signed:

        params["timestamp"] = int(
            time.time() * 1000
        )

        params["recvWindow"] = 5000

        query = urllib.parse.urlencode(
            params
        )

        params["signature"] = hmac.new(
            secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

    query = urllib.parse.urlencode(
        params
    )

    request = urllib.request.Request(
        base + path + "?" + query,
        headers={
            "X-MBX-APIKEY": key
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=12
        ) as response:

            return (
                response.status,
                json.loads(
                    response.read().decode()
                )
            )

    except urllib.error.HTTPError as error:

        raw = error.read().decode(
            errors="replace"
        )

        try:
            data = json.loads(raw)
        except Exception:
            data = {
                "raw": raw[:300]
            }

        return error.code, data


status, public = get(
    "/fapi/v1/time"
)

print(
    "PUBLIC_STATUS=",
    status
)

if status != 200:
    raise SystemExit(10)


status, exchange_info = get(
    "/fapi/v1/exchangeInfo"
)

print(
    "EXCHANGEINFO_STATUS=",
    status
)

if status != 200:
    raise SystemExit(11)


status, account = get(
    "/fapi/v2/account",
    signed=True
)

print(
    "AUTH_STATUS=",
    status
)

if (
    isinstance(account, dict)
    and account.get("code") == -2015
):

    print("AUTH=-2015")
    raise SystemExit(2015)

if status != 200:

    print(
        "AUTH_ERROR_CODE=",
        account.get("code")
        if isinstance(account, dict)
        else "UNKNOWN"
    )

    raise SystemExit(12)

print(
    "TESTNET_AUTH=PASS"
)

print(
    "ACCOUNT_ASSET_COUNT=",
    len(account.get("assets", []))
)

print(
    "ACCOUNT_POSITION_COUNT=",
    len(account.get("positions", []))
)
