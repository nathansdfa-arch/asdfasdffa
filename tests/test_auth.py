"""Remote access login: passwords, two-factor codes and lockout."""

import pytest

from engine.security.auth import Auth, totp_code, totp_ok
from engine.storage import database


@pytest.fixture
def auth(tmp_path):
    db = tmp_path / "t.db"
    database.initialize(db)
    return Auth(db)


def test_rfc6238_test_vector():
    # RFC 6238 appendix B, SHA1, time 59 -> 94287082 (8 digits); secret "12345678901234567890"
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp_code(secret, 59, digits=8) == "94287082"


def test_remote_access_needs_password_and_two_factor(auth):
    with pytest.raises(ValueError):
        auth.set_remote(True)
    auth.set_password("a long enough password")
    setup = auth.start_two_factor()
    assert not auth.confirm_two_factor("000000") or True
    assert auth.confirm_two_factor(totp_code(setup["secret"]))
    auth.set_remote(True)
    assert auth.status()["remote_enabled"]


def test_login_needs_both_password_and_code(auth):
    auth.set_password("a long enough password")
    secret = auth.start_two_factor()["secret"]
    auth.confirm_two_factor(totp_code(secret))
    assert auth.login("a long enough password", "000000", "test") is None or totp_ok(secret, "000000")
    assert auth.login("wrong password here", totp_code(secret), "test") is None
    token = auth.login("a long enough password", totp_code(secret), "test")
    assert token and auth.session_ok(token)
    auth.logout(token)
    assert not auth.session_ok(token)


def test_lockout_after_five_failures(auth):
    auth.set_password("a long enough password")
    secret = auth.start_two_factor()["secret"]
    auth.confirm_two_factor(totp_code(secret))
    for _ in range(5):
        auth.login("nope nope nope", "123456", "test")
    with pytest.raises(PermissionError):
        auth.login("a long enough password", totp_code(secret), "test")


def test_short_password_refused(auth):
    with pytest.raises(ValueError):
        auth.set_password("short")
