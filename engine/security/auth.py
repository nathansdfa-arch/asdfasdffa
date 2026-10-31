"""Login, two-factor codes and sessions for remote access (bible sections 4 and 11, phase 12).

The rules:
  - On this computer (the desktop window, or a browser at 127.0.0.1) no login is needed.
  - From any other device, remote access must be switched on first, and that
    needs a password, two-factor authentication and an encrypted (HTTPS) connection.
  - Two-factor codes are the standard 6-digit codes from an authenticator app
    (Google Authenticator, Microsoft Authenticator, 1Password and so on).
  - Five wrong logins in a row lock logins for 5 minutes.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import struct
import time
from pathlib import Path

from engine.storage.database import connect

log = logging.getLogger(__name__)

SESSION_HOURS = 12
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300


# ---------------------------------------------------------------------------
# Two-factor codes (TOTP, RFC 6238)
# ---------------------------------------------------------------------------


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((time.time() if at is None else at) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** digits).zfill(digits)


def totp_ok(secret: str, code: str, at: float | None = None) -> bool:
    """Accepts the current code and the ones either side, allowing for clock drift."""
    now = time.time() if at is None else at
    code = (code or "").strip().replace(" ", "")
    return any(hmac.compare_digest(totp_code(secret, now + drift), code) for drift in (-30, 0, 30))


def totp_uri(secret: str, label: str = "owner") -> str:
    return f"otpauth://totp/TradingApp:{label}?secret={secret}&issuer=TradingApp&digits=6&period=30"


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# The auth store
# ---------------------------------------------------------------------------


class Auth:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._failures = 0
        self._locked_until = 0.0

    def _get(self, key: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM auth WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set(self, key: str, value: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO auth (key, value) VALUES (?, ?)", (key, value))

    def status(self) -> dict:
        return {
            "password_set": self._get("password_hash") is not None,
            "two_factor_set": self._get("totp_confirmed") == "yes",
            "remote_enabled": self._get("remote_enabled") == "yes",
            "remote_port": int(self._get("remote_port") or 8443),
        }

    def set_password(self, password: str) -> None:
        if len(password) < 12:
            raise ValueError("Use a password of at least 12 characters.")
        self._set("password_hash", hash_password(password))
        self.end_all_sessions()
        log.info("Remote access password changed")

    def start_two_factor(self) -> dict:
        """Make a new secret. It only counts once a code from the app is confirmed."""
        secret = new_totp_secret()
        self._set("totp_pending", secret)
        return {"secret": secret, "uri": totp_uri(secret)}

    def confirm_two_factor(self, code: str) -> bool:
        pending = self._get("totp_pending")
        if not pending or not totp_ok(pending, code):
            return False
        self._set("totp_secret", pending)
        self._set("totp_confirmed", "yes")
        self.end_all_sessions()
        log.info("Two-factor authentication set up")
        return True

    def set_remote(self, enabled: bool, port: int | None = None) -> None:
        status = self.status()
        if enabled and not (status["password_set"] and status["two_factor_set"]):
            raise ValueError("Set a password and two-factor authentication before switching on remote access.")
        self._set("remote_enabled", "yes" if enabled else "no")
        if port:
            self._set("remote_port", str(port))
        log.warning("Remote access switched %s (takes effect when the app restarts)", "ON" if enabled else "OFF")

    def login(self, password: str, code: str, client: str) -> str | None:
        """Returns a session token, or None. Locks logins after repeated failures."""
        now = time.time()
        if now < self._locked_until:
            raise PermissionError("Too many wrong attempts. Try again in a few minutes.")
        stored = self._get("password_hash")
        secret = self._get("totp_secret")
        if stored and secret and check_password(password, stored) and totp_ok(secret, code):
            self._failures = 0
            token = secrets.token_urlsafe(32)
            with connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO sessions (token_hash, created_at, expires_at, client) VALUES (?, ?, ?, ?)",
                    (hashlib.sha256(token.encode()).hexdigest(), now, now + SESSION_HOURS * 3600, client),
                )
            log.info("Remote login from %s", client)
            return token
        self._failures += 1
        log.warning("Failed remote login from %s", client)
        if self._failures >= MAX_FAILURES:
            self._locked_until = now + LOCKOUT_SECONDS
            self._failures = 0
        return None

    def session_ok(self, token: str | None) -> bool:
        if not token:
            return False
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return bool(row and row["expires_at"] > time.time())

    def logout(self, token: str | None) -> None:
        if token:
            with connect(self.db_path) as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))

    def end_all_sessions(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM sessions")


def make_self_signed_certificate(folder: Path) -> tuple[Path, Path]:
    """An encryption certificate for HTTPS. Browsers will warn that it is self-signed;
    see NEEDS_NATHAN.md for the recommended private-network option instead."""
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TradingApp")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + timedelta(days=825))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path
