import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    username: str | None = None
    first_name: str | None = None


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: int | None = None,
) -> TelegramUser:
    if not init_data:
        raise TelegramAuthError("Missing Telegram init data")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("duplicate init data parameter")
        values = dict(pairs)
        received_hash = values.pop("hash")
        auth_date = int(values["auth_date"])
        user_payload = json.loads(values["user"])
        if not isinstance(user_payload, dict):
            raise TypeError("user must be an object")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramAuthError("Malformed Telegram init data") from exc

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(received_hash, expected_hash):
        raise TelegramAuthError("Invalid Telegram init data signature")

    current_time = int(time.time()) if now is None else now
    if auth_date > current_time or current_time - auth_date > max_age_seconds:
        raise TelegramAuthError("Expired Telegram init data")

    try:
        user_id = int(user_payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramAuthError("Telegram user is missing") from exc

    return TelegramUser(
        id=user_id,
        username=user_payload.get("username"),
        first_name=user_payload.get("first_name"),
    )
