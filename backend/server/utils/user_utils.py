"""
User ID generation utilities
Provides username validation and user_id auto-generation functionality
"""

import re

from pypinyin import lazy_pinyin, Style


def to_pinyin(text: str) -> str:
    """
    Converts Chinese text to Pinyin
    Uses pypinyin library for conversion
    """
    # Use pypinyin for conversion
    pinyin_list = lazy_pinyin(text, style=Style.NORMAL)
    return "".join(pinyin_list)


def validate_username(username: str) -> tuple[bool, str]:
    """
    Validates username format

    Args:
        username: Username string

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not username:
        return False, "Username cannot be empty"

    if len(username) < 2:
        return False, "Username must be at least 2 characters long"

    if len(username) > 20:
        return False, "Username cannot exceed 20 characters"

    # Check for disallowed characters
    # Allows Chinese, English, numbers, and underscores
    if not re.match(r"^[\u4e00-\u9fa5a-zA-Z0-9_]+$", username):
        return False, "Username can only contain Chinese, English, numbers, and underscores"

    return True, ""


def generate_user_id(username: str) -> str:
    """
    Generates user_id based on username

    Args:
        username: Username string

    Returns:
        str: Generated user_id
    """
    # 1. Basic cleanup
    username = username.strip()

    # 2. Convert to pinyin (if contains Chinese)
    user_id = to_pinyin(username)

    # 3. Handle special characters, keeping only alphanumeric and underscores
    user_id = re.sub(r"[^a-zA-Z0-9_]", "", user_id)

    # 4. Ensure it doesn't start with a digit
    if user_id and user_id[0].isdigit():
        user_id = "u" + user_id

    # 5. Fallback if empty or too short
    if len(user_id) < 2:
        user_id = "user" + str(hash(username) % 10000).zfill(4)

    # 6. Length limit
    if len(user_id) > 20:
        user_id = user_id[:20]

    return user_id.lower()


def generate_unique_user_id(username: str, existing_user_ids: list[str]) -> str:
    """
    Generates a unique user_id, adding a numeric suffix if duplicated

    Args:
        username: Username string
        existing_user_ids: List of existing user_ids

    Returns:
        str: Unique user_id
    """
    base_user_id = generate_user_id(username)

    # If no conflict, return directly
    if base_user_id not in existing_user_ids:
        return base_user_id

    # Add numeric suffix if conflict exists
    counter = 1
    while True:
        candidate = f"{base_user_id}{counter}"
        if candidate not in existing_user_ids:
            return candidate
        counter += 1

        # Prevent infinite loop
        if counter > 9999:
            # Use timestamp as fallback suffix
            import time

            candidate = f"{base_user_id}{int(time.time()) % 10000}"
            return candidate


def is_valid_phone_number(phone: str) -> bool:
    """
    Validates phone number format (supports Indonesian mobile formats)

    Args:
        phone: Phone number string

    Returns:
        bool: True if valid
    """
    if not phone:
        return False

    # Remove spaces and special characters
    phone = re.sub(r"[\s\-\(\)]", "", phone)

    # Indonesian mobile format:
    # - Local: 08xxxxxxxxxx (10-13 digits)
    # - Intl : 628xxxxxxxxxx or +628xxxxxxxxxx
    pattern = r"^(?:\+62|62|0)8[1-9]\d{7,10}$"

    return bool(re.match(pattern, phone))


def normalize_phone_number(phone: str) -> str:
    """
    Normalizes phone number format

    Args:
        phone: Raw phone number

    Returns:
        str: Normalized phone number
    """
    if not phone:
        return ""

    # Remove all non-numeric characters
    phone = re.sub(r"\D", "", phone)

    # Normalize Indonesian international format to local format (e.g. 62812... -> 0812...)
    if phone.startswith("62"):
        phone = f"0{phone[2:]}"
    elif phone.startswith("8"):
        phone = f"0{phone}"

    # Keep normalized local format if valid
    if re.match(r"^08[1-9]\d{7,10}$", phone):
        return phone

    return phone
