import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.telegram_auth import TelegramAuthError, validate_init_data


def make_init_data(token: str, user_id: int = 42, auth_date: int = 1_700_000_000) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "query-id",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_validate_init_data_returns_user() -> None:
    result = validate_init_data(
        make_init_data("bot-token"),
        bot_token="bot-token",
        max_age_seconds=60,
        now=1_700_000_030,
    )
    assert result.id == 42
    assert result.first_name == "Test"


@pytest.mark.parametrize("value", ["", "auth_date=1", "auth_date=abc&hash=bad"])
def test_validate_init_data_rejects_malformed(value: str) -> None:
    with pytest.raises(TelegramAuthError):
        validate_init_data(value, bot_token="bot-token", max_age_seconds=60, now=1_700_000_030)


def test_validate_init_data_rejects_bad_signature() -> None:
    data = make_init_data("bot-token").replace("query-id", "other")
    with pytest.raises(TelegramAuthError, match="signature"):
        validate_init_data(data, bot_token="bot-token", max_age_seconds=60, now=1_700_000_030)


def test_validate_init_data_rejects_duplicate_parameters() -> None:
    token = "bot-token"
    with pytest.raises(TelegramAuthError, match="Malformed"):
        validate_init_data(
            f"{make_init_data(token)}&auth_date=1700000000",
            bot_token=token,
            max_age_seconds=60,
            now=1_700_000_030,
        )


def test_validate_init_data_rejects_non_object_user() -> None:
    token = "bot-token"
    values = {"auth_date": "1700000000", "user": "[]"}
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(TelegramAuthError, match="Malformed"):
        validate_init_data(
            urlencode(values), bot_token=token, max_age_seconds=60, now=1_700_000_030
        )


def test_validate_init_data_rejects_expired_data() -> None:
    with pytest.raises(TelegramAuthError, match="Expired"):
        validate_init_data(
            make_init_data("bot-token", auth_date=1_700_000_000),
            bot_token="bot-token",
            max_age_seconds=60,
            now=1_700_000_061,
        )
