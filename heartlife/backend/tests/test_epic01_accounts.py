from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import User


def _register_and_login(
    client: TestClient,
    account: str = "alice01",
    password: str = "SafePass123!",
    nickname: str = "小禾",
    timezone: str = "Asia/Shanghai",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": password, "nickname": nickname, "timezone": timezone},
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert login.status_code == 200, login.text
    data = login.json()
    return data["user"], data["csrf_token"]


def test_t0101_register_creates_member_and_hashes_password(client: TestClient, db_session: Session):
    """T-0101: Valid registration creates active member and never stores plaintext password."""
    res = client.post(
        "/api/v1/auth/register",
        json={"account": "Alice_01", "password": "MySecretPassword99!", "nickname": "林晓禾"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["user"]["account"] == "alice_01"
    assert body["user"]["roles"] == ["member"]
    assert "password" not in body["user"]

    u = db_session.scalar(select(User).where(User.account == "alice_01"))
    assert u is not None
    assert u.password_hash != "MySecretPassword99!"
    assert u.password_hash.startswith("$argon2")
    assert u.roles == "member"


def test_t0102_duplicate_or_invalid_registration_rejected(client: TestClient, db_session: Session):
    """T-0102: Duplicate account or invalid fields rejected without creating second account."""
    r1 = client.post(
        "/api/v1/auth/register",
        json={"account": "dupuser", "password": "ValidPassword1!", "nickname": "用户一"},
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/v1/auth/register",
        json={"account": "DUPUSER", "password": "ValidPassword2!", "nickname": "用户二"},
    )
    assert r2.status_code == 409

    # Invalid short password / bad account chars / bad timezone
    assert client.post(
        "/api/v1/auth/register",
        json={"account": "ab", "password": "ValidPassword1!", "nickname": "短账号"},
    ).status_code == 422
    assert client.post(
        "/api/v1/auth/register",
        json={"account": "goodacc", "password": "123", "nickname": "短密码"},
    ).status_code == 422
    assert client.post(
        "/api/v1/auth/register",
        json={"account": "goodacc2", "password": "ValidPassword1!", "nickname": "坏时区", "timezone": "Mars/Phobos"},
    ).status_code == 422

    count = db_session.scalar(select(func.count()).select_from(User))
    assert count == 1


def test_t0103_login_success_and_wrong_password_generic_error(app_instance):
    """T-0103: Correct password creates HttpOnly session; wrong password fails without leaking internals."""
    with TestClient(app_instance) as c1:
        c1.post(
            "/api/v1/auth/register",
            json={"account": "bob01", "password": "BobPassword123!", "nickname": "远山"},
        )

    with TestClient(app_instance) as c_bad:
        bad = c_bad.post("/api/v1/auth/login", json={"account": "bob01", "password": "WrongPassword!"})
        assert bad.status_code == 401
        err = bad.json()["error"]
        assert "argon2" not in err["message"].lower()
        assert "sql" not in err["message"].lower()
        assert c_bad.get("/api/v1/me").status_code == 401

        missing = c_bad.post("/api/v1/auth/login", json={"account": "nonexistent", "password": "WrongPassword!"})
        assert missing.status_code == 401
        assert missing.json()["error"]["message"] == err["message"]

    with TestClient(app_instance) as c_ok:
        ok = c_ok.post("/api/v1/auth/login", json={"account": "bob01", "password": "BobPassword123!"})
        assert ok.status_code == 200
        assert "hl_session" in c_ok.cookies
        me = c_ok.get("/api/v1/me")
        assert me.status_code == 200
        assert me.json()["nickname"] == "远山"


def test_t0104_unauthenticated_logout_and_session_expiry(app_instance, fake_clock: FakeClock):
    """T-0104: Unauthenticated, logged-out, or expired sessions get 401 on private endpoints."""
    with TestClient(app_instance) as anon:
        assert anon.get("/api/v1/me").status_code == 401

    with TestClient(app_instance) as c:
        _, csrf = _register_and_login(c, account="expuser")
        saved_session_cookie = c.cookies.get("hl_session")
        assert c.get("/api/v1/me").status_code == 200

        out = c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert out.status_code == 200
        assert c.get("/api/v1/me").status_code == 401

        # Replaying old cookie after logout still rejected
        c.cookies.set("hl_session", saved_session_cookie)
        assert c.get("/api/v1/me").status_code == 401

    with TestClient(app_instance) as c2:
        login = c2.post("/api/v1/auth/login", json={"account": "expuser", "password": "SafePass123!"})
        assert login.status_code == 200
        fake_clock.advance(hours=200)  # Exceeds default 168h TTL
        assert c2.get("/api/v1/me").status_code == 401


def test_t0105_forbid_role_escalation_and_editing_other_profile(app_instance, db_session: Session):
    """T-0105: Normal user cannot forge roles or modify another user's profile."""
    with TestClient(app_instance) as ca:
        ua, csrf_a = _register_and_login(ca, account="user_a", nickname="甲")
        # Attempt role escalation on register
        escalate_reg = ca.post(
            "/api/v1/auth/register",
            json={
                "account": "hacker",
                "password": "SafePass123!",
                "nickname": "黑客",
                "roles": "moderator,editor",
            },
        )
        assert escalate_reg.status_code == 422

        # Attempt role escalation or owner forge on PATCH /me
        escalate_patch = ca.patch(
            "/api/v1/me",
            json={"nickname": "甲改", "roles": "moderator"},
            headers={"X-CSRF-Token": csrf_a},
        )
        assert escalate_patch.status_code == 422

        db_session.expire_all()
        u = db_session.scalar(select(User).where(User.id == ua["id"]))
        assert u is not None
        assert u.roles == "member"
        assert u.nickname == "甲"


def test_t0106_csrf_protection_enforced_on_write_endpoints(client: TestClient):
    """T-0106: Valid session cookie without valid CSRF token gets 403; valid CSRF succeeds."""
    _, csrf = _register_and_login(client, account="csrf_user")

    no_csrf = client.patch("/api/v1/me", json={"nickname": "无令牌"})
    assert no_csrf.status_code == 403

    bad_csrf = client.patch("/api/v1/me", json={"nickname": "假令牌"}, headers={"X-CSRF-Token": "wrong-token"})
    assert bad_csrf.status_code == 403

    good_csrf = client.patch(
        "/api/v1/me",
        json={"nickname": "新昵称", "bio": "安静记录每一天"},
        headers={"X-CSRF-Token": csrf},
    )
    assert good_csrf.status_code == 200
    assert good_csrf.json()["nickname"] == "新昵称"
    assert good_csrf.json()["bio"] == "安静记录每一天"


def test_t0107_login_rate_limit_and_clock_recovery(app_instance, fake_clock: FakeClock):
    """T-0107: Repeated failed logins trigger 429; advancing fake clock past window recovers."""
    with TestClient(app_instance) as c:
        c.post(
            "/api/v1/auth/register",
            json={"account": "rateuser", "password": "RightPassword1!", "nickname": "限流测试"},
        )
        for _ in range(5):
            r = c.post("/api/v1/auth/login", json={"account": "rateuser", "password": "WrongPassword!"})
            assert r.status_code == 401

        blocked = c.post("/api/v1/auth/login", json={"account": "rateuser", "password": "RightPassword1!"})
        assert blocked.status_code == 429

        # Advance clock past 900s window
        fake_clock.advance(seconds=905)
        recovered = c.post("/api/v1/auth/login", json={"account": "rateuser", "password": "RightPassword1!"})
        assert recovered.status_code == 200
