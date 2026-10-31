"""Broker passwords and API keys, kept in the operating system's secure storage.

On Windows this is the Windows Credential Manager (bible section 11). They
are never written to the database, the logs or source control. The
"keyring" package talks to the Credential Manager for us.
"""

import logging

log = logging.getLogger(__name__)

SERVICE = "TradingApp"


def _keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def save_secret(account_id: str, name: str, value: str) -> bool:
    keyring = _keyring()
    if keyring is None:
        log.error("Secure storage isn't available, so the secret was not saved.")
        return False
    keyring.set_password(SERVICE, f"{account_id}:{name}", value)
    log.info("Saved secret '%s' for account %s in secure storage", name, account_id)   # never the value
    return True


def load_secret(account_id: str, name: str) -> str | None:
    keyring = _keyring()
    if keyring is None:
        return None
    try:
        return keyring.get_password(SERVICE, f"{account_id}:{name}")
    except Exception:
        log.exception("Could not read from secure storage")
        return None


def has_secret(account_id: str, name: str) -> bool:
    return load_secret(account_id, name) is not None


def delete_secret(account_id: str, name: str) -> None:
    keyring = _keyring()
    if keyring is None:
        return
    try:
        keyring.delete_password(SERVICE, f"{account_id}:{name}")
    except Exception:
        pass
