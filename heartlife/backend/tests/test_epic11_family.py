from __future__ import annotations

import json
from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import Checkin, FamilyInvite, JournalEntry, Plan, PlanVersion


def _register_and_login(
    client: TestClient,
    account: str,
    nickname: str = "家庭成员",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": "SafePassword123!", "nickname": nickname},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/auth/login",
        json={"account": account, "password": "SafePassword123!"},
    )
    assert login.status_code == 200, login.text
    data = login.json()
    return data["user"], data["csrf_token"]


def test_t1101_family_invite_hashed_one_time_24h_ttl_and_no_self_accept(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-1101: Invite stores only code_hash; rejects invalid (404), self-accept (422), expired >24h (422), and reuse (409)."""
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with (
        TestClient(app_instance) as c_parent,
        TestClient(app_instance) as c_child,
        TestClient(app_instance) as c_other,
    ):
        u_parent, csrf_p = _register_and_login(c_parent, "fam_parent", "父亲")
        _, csrf_c = _register_and_login(c_child, "fam_child", "女儿")
        _, csrf_o = _register_and_login(c_other, "fam_other", "旁人")

        inv_res = c_parent.post(
            "/api/v1/me/family/invites",
            json={"share_plan_summary": True, "share_weekly_sleep": True, "share_weekly_activity": False},
            headers={"X-CSRF-Token": csrf_p},
        )
        assert inv_res.status_code == 201, inv_res.text
        code = inv_res.json()["invite_code"]
        inv_id = inv_res.json()["invite_id"]

        # DB stores hash, never raw code
        inv_row = db_session.get(FamilyInvite, inv_id)
        assert inv_row is not None
        assert inv_row.code_hash != code

        # Invalid code -> 404
        assert c_child.post(
            "/api/v1/me/family/accept",
            json={"invite_code": "nonexistent-code-xyz"},
            headers={"X-CSRF-Token": csrf_c},
        ).status_code == 404

        # Self-accept -> 422
        assert c_parent.post(
            "/api/v1/me/family/accept",
            json={"invite_code": code},
            headers={"X-CSRF-Token": csrf_p},
        ).status_code == 422

        # Child accepts -> 200
        acc_ok = c_child.post(
            "/api/v1/me/family/accept",
            json={"invite_code": code},
            headers={"X-CSRF-Token": csrf_c},
        )
        assert acc_ok.status_code == 200, acc_ok.text
        assert acc_ok.json()["granter_id"] == u_parent["id"]

        # Reusing same code -> 409
        reuse = c_other.post(
            "/api/v1/me/family/accept",
            json={"invite_code": code},
            headers={"X-CSRF-Token": csrf_o},
        )
        assert reuse.status_code == 409

        # Expired invite (>24h) -> 422
        inv_exp = c_parent.post(
            "/api/v1/me/family/invites",
            json={"share_plan_summary": True},
            headers={"X-CSRF-Token": csrf_p},
        ).json()["invite_code"]
        fake_clock.advance(hours=25)
        expired_res = c_other.post(
            "/api/v1/me/family/accept",
            json={"invite_code": inv_exp},
            headers={"X-CSRF-Token": csrf_o},
        )
        assert expired_res.status_code == 422


def test_t1102_shared_view_blocks_unauthorized_users_and_lists_grants(
    app_instance,
):
    """T-1102: Without active grant GET /family/shared/{granter_id} returns 403; authorized viewer sees grant list."""
    with (
        TestClient(app_instance) as c_granter,
        TestClient(app_instance) as c_viewer,
        TestClient(app_instance) as c_stranger,
    ):
        u_g, csrf_g = _register_and_login(c_granter, "grant_owner", "长辈")
        u_v, csrf_v = _register_and_login(c_viewer, "grant_viewer", "家属")
        _register_and_login(c_stranger, "grant_stranger", "陌生人")

        # Before accepting, both viewer and stranger get 403
        assert c_viewer.get(f"/api/v1/family/shared/{u_g['id']}").status_code == 403
        assert c_stranger.get(f"/api/v1/family/shared/{u_g['id']}").status_code == 403

        code = c_granter.post(
            "/api/v1/me/family/invites",
            json={"share_plan_summary": True},
            headers={"X-CSRF-Token": csrf_g},
        ).json()["invite_code"]
        assert c_viewer.post(
            "/api/v1/me/family/accept",
            json={"invite_code": code},
            headers={"X-CSRF-Token": csrf_v},
        ).status_code == 200

        assert c_viewer.get(f"/api/v1/family/shared/{u_g['id']}").status_code == 200
        assert c_stranger.get(f"/api/v1/family/shared/{u_g['id']}").status_code == 403

        g_list = c_granter.get("/api/v1/me/family/grants").json()
        v_list = c_viewer.get("/api/v1/me/family/grants").json()
        assert len(g_list["granted_by_me"]) == 1
        assert g_list["granted_by_me"][0]["viewer_id"] == u_v["id"]
        assert len(v_list["granted_to_me"]) == 1
        assert v_list["granted_to_me"][0]["granter_id"] == u_g["id"]


def test_t1103_shared_summary_strictly_filters_fields_and_never_leaks_private_journal_details(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-1103: GET /family/shared/{granter_id} returns ONLY enabled summary metrics; NEVER returns journals/note/mood/symptom_tags."""
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as c_granter, TestClient(app_instance) as c_viewer:
        u_g, csrf_g = _register_and_login(c_granter, "filter_granter", "母亲")
        _, csrf_v = _register_and_login(c_viewer, "filter_viewer", "儿子")

        plan = Plan(owner_id=u_g["id"], title="饭后散步", active=True)
        db_session.add(plan)
        db_session.flush()
        db_session.add_all(
            [
                PlanVersion(
                    plan_id=plan.id,
                    version_num=1,
                    effective_from=date(2026, 11, 23),
                    weekday_mask=127,
                    active=True,
                    start_date=date(2026, 11, 23),
                ),
                Checkin(plan_id=plan.id, local_date=date(2026, 11, 24), completed=True),
                JournalEntry(
                    user_id=u_g["id"],
                    local_date=date(2026, 11, 24),
                    sleep_minutes=450,
                    activity_minutes=35,
                    mood="有些焦虑",
                    symptom_tags_json=json.dumps(["胸闷自述敏感词"]),
                    note="绝密日记原文不可对家人可见",
                ),
            ]
        )
        db_session.commit()

        # Enable plan_summary=True, weekly_sleep=True, weekly_activity=False
        code = c_granter.post(
            "/api/v1/me/family/invites",
            json={
                "share_plan_summary": True,
                "share_weekly_sleep": True,
                "share_weekly_activity": False,
            },
            headers={"X-CSRF-Token": csrf_g},
        ).json()["invite_code"]
        c_viewer.post("/api/v1/me/family/accept", json={"invite_code": code}, headers={"X-CSRF-Token": csrf_v})

        res = c_viewer.get(f"/api/v1/family/shared/{u_g['id']}")
        assert res.status_code == 200, res.text
        shared = res.json()

        assert shared["granter_nickname"] == "母亲"
        assert shared["plan_summary"] == {"due": 3, "completed": 1, "completion_rate": 0.3333}
        assert shared["weekly_sleep"] == {"valid_days": 1, "mean_minutes": 450.0}
        assert "weekly_activity" not in shared

        # Private fields strictly absent
        for forbidden_key in ("journals", "note", "mood", "mood_distribution", "symptom_tags", "daily_series"):
            assert forbidden_key not in shared
        assert "绝密日记原文不可对家人可见" not in res.text
        assert "有些焦虑" not in res.text
        assert "胸闷自述敏感词" not in res.text


def test_t1104_revoking_grant_immediately_blocks_subsequent_access(
    app_instance,
):
    """T-1104: Either granter or viewer can DELETE grant, immediately causing GET /family/shared to return 403."""
    with (
        TestClient(app_instance) as c_granter,
        TestClient(app_instance) as c_viewer,
        TestClient(app_instance) as c_third,
    ):
        u_g, csrf_g = _register_and_login(c_granter, "rev_granter", "长辈甲")
        _, csrf_v = _register_and_login(c_viewer, "rev_viewer", "家属乙")
        _, csrf_t = _register_and_login(c_third, "rev_third", "路人丙")

        code = c_granter.post(
            "/api/v1/me/family/invites",
            json={"share_plan_summary": True},
            headers={"X-CSRF-Token": csrf_g},
        ).json()["invite_code"]
        grant = c_viewer.post(
            "/api/v1/me/family/accept",
            json={"invite_code": code},
            headers={"X-CSRF-Token": csrf_v},
        ).json()
        grant_id = grant["id"]

        # Third party cannot revoke -> 403
        assert c_third.delete(
            f"/api/v1/me/family/grants/{grant_id}",
            headers={"X-CSRF-Token": csrf_t},
        ).status_code == 403

        # Granter revokes -> 200, viewer immediately gets 403
        del_res = c_granter.delete(
            f"/api/v1/me/family/grants/{grant_id}",
            headers={"X-CSRF-Token": csrf_g},
        )
        assert del_res.status_code == 200
        assert c_viewer.get(f"/api/v1/family/shared/{u_g['id']}").status_code == 403


def test_t1105_only_granter_can_patch_grant_sharing_scope(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-1105: Viewer or third party attempting PATCH /me/family/grants/{id} gets 403; granter succeeds."""
    fake_clock.set(datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc))

    with (
        TestClient(app_instance) as c_granter,
        TestClient(app_instance) as c_viewer,
        TestClient(app_instance) as c_third,
    ):
        u_g, csrf_g = _register_and_login(c_granter, "patch_granter", "授权人")
        _, csrf_v = _register_and_login(c_viewer, "patch_viewer", "查看人")
        _, csrf_t = _register_and_login(c_third, "patch_third", "旁观者")

        db_session.add(
            JournalEntry(
                user_id=u_g["id"],
                local_date=date(2026, 11, 25),
                sleep_minutes=420,
                activity_minutes=50,
            )
        )
        db_session.commit()

        code = c_granter.post(
            "/api/v1/me/family/invites",
            json={"share_plan_summary": True, "share_weekly_sleep": False, "share_weekly_activity": False},
            headers={"X-CSRF-Token": csrf_g},
        ).json()["invite_code"]
        grant = c_viewer.post(
            "/api/v1/me/family/accept",
            json={"invite_code": code},
            headers={"X-CSRF-Token": csrf_v},
        ).json()
        grant_id = grant["id"]

        # Viewer attempting to escalate own permissions -> 403
        v_patch = c_viewer.patch(
            f"/api/v1/me/family/grants/{grant_id}",
            json={"share_weekly_sleep": True, "share_weekly_activity": True},
            headers={"X-CSRF-Token": csrf_v},
        )
        assert v_patch.status_code == 403

        # Third party attempting PATCH -> 403
        t_patch = c_third.patch(
            f"/api/v1/me/family/grants/{grant_id}",
            json={"share_weekly_sleep": True},
            headers={"X-CSRF-Token": csrf_t},
        )
        assert t_patch.status_code == 403

        # Verify shared response still lacks sleep & activity
        s_before = c_viewer.get(f"/api/v1/family/shared/{u_g['id']}").json()
        assert "weekly_sleep" not in s_before
        assert "weekly_activity" not in s_before

        # Granter enables weekly_activity -> 200
        g_patch = c_granter.patch(
            f"/api/v1/me/family/grants/{grant_id}",
            json={"share_weekly_activity": True},
            headers={"X-CSRF-Token": csrf_g},
        )
        assert g_patch.status_code == 200
        assert g_patch.json()["share_weekly_activity"] is True

        s_after = c_viewer.get(f"/api/v1/family/shared/{u_g['id']}").json()
        assert s_after["weekly_activity"] == {"valid_days": 1, "total_minutes": 50}
        assert "weekly_sleep" not in s_after
