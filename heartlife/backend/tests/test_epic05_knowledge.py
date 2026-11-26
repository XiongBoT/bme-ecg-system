from __future__ import annotations

from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import ArticleRevision, ReadingDailyLog, ReadingHistory, User


def _register_and_login(
    client: TestClient,
    db_session: Session | None = None,
    *,
    account: str,
    nickname: str,
    roles: str = "member",
    timezone_name: str = "Asia/Shanghai",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "account": account,
            "password": "SafePassword123!",
            "nickname": nickname,
            "timezone": timezone_name,
        },
    )
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["user"]["id"]
    if db_session is not None and roles != "member":
        u = db_session.scalar(select(User).where(User.id == user_id))
        assert u is not None
        u.roles = roles
        db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"account": account, "password": "SafePassword123!"},
    )
    assert login.status_code == 200, login.text
    data = login.json()
    return data["user"], data["csrf_token"]


VALID_SOURCES = [
    {
        "title": "WHO - Physical Activity Fact Sheet",
        "url": "https://www.who.int/news-room/fact-sheets/detail/physical-activity",
        "accessed_at": "2026-11-26",
    }
]

VALID_REVIEW = {
    "reviewer": "课程内容核验组",
    "review_type": "课程内容审核",
    "reviewed_at": "2026-11-26",
    "note": "已核对公开指南出处，仅作日常健康生活参考。",
}


def _create_and_publish_article(
    editor_client: TestClient,
    editor_csrf: str,
    *,
    title: str,
    category: str = "睡眠与休息",
    summary: str = "规律作息有助于维持自主神经平衡。",
    body: str = "建议成年人保持每晚 7 至 9 小时规律睡眠，睡前减少强光刺激。",
) -> dict:
    created = editor_client.post(
        "/api/v1/editor/articles",
        json={
            "title": title,
            "category": category,
            "summary": summary,
            "body": body,
            "author_byline": "HeartLife 课程科普组",
            "scope_note": "仅用于日常健康生活科普参考，不作为临床诊断或用药建议。",
            "sources": VALID_SOURCES,
            "review_record": VALID_REVIEW,
        },
        headers={"X-CSRF-Token": editor_csrf},
    )
    assert created.status_code == 201, created.text
    art_id = created.json()["id"]
    pub = editor_client.post(
        f"/api/v1/editor/articles/{art_id}/publish",
        json={},
        headers={"X-CSRF-Token": editor_csrf},
    )
    assert pub.status_code == 200, pub.text
    return pub.json()


def test_t0501_public_list_categories_search_pagination_and_draft_isolation(
    app_instance,
    db_session: Session,
    fake_clock: FakeClock,
):
    """T-0501: Public/member list, categories, search & detail return ONLY published articles with cursor pagination."""
    with TestClient(app_instance) as ed_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0501", nickname="科普编辑", roles="member,editor"
        )
        # Create 3 published articles at distinct timestamps and 1 draft article
        a1 = _create_and_publish_article(
            ed_client,
            ed_csrf,
            title="睡前放松呼吸指南",
            category="睡眠与休息",
            summary="平缓腹式呼吸练习",
            body="每分钟六次平缓呼吸帮助放松。",
        )
        fake_clock.advance(minutes=10)
        a2 = _create_and_publish_article(
            ed_client,
            ed_csrf,
            title="日常温和步行建议",
            category="运动与习惯",
            summary="饭后散步二十分钟",
            body="循序渐进开展日常步行活动。",
        )
        fake_clock.advance(minutes=10)
        a3 = _create_and_publish_article(
            ed_client,
            ed_csrf,
            title="固定起床时间的重要性",
            category="睡眠与休息",
            summary="稳定生物钟节律",
            body="周末与工作日尽量保持相近起床时间。",
        )

        draft_res = ed_client.post(
            "/api/v1/editor/articles",
            json={
                "title": "未发布内部草稿不应公开检索词XYZ",
                "category": "睡眠与休息",
                "summary": "草稿摘要",
                "body": "草稿正文不应出现在公开接口。",
            },
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert draft_res.status_code == 201
        draft_id = draft_res.json()["id"]

    with TestClient(app_instance) as anon:
        cats_res = anon.get("/api/v1/articles/categories")
        assert cats_res.status_code == 200
        cats = cats_res.json()["categories"]
        assert "睡眠与休息" in cats
        assert "运动与习惯" in cats
        assert "心脏基础知识" in cats

        # Cursor pagination ordered by (published_at DESC, id DESC) -> a3, a2, a1
        p1 = anon.get("/api/v1/articles", params={"limit": 2})
        assert p1.status_code == 200
        p1_data = p1.json()
        assert [item["id"] for item in p1_data["items"]] == [a3["id"], a2["id"]]
        assert p1_data["next_cursor"] is not None

        p2 = anon.get("/api/v1/articles", params={"limit": 2, "cursor": p1_data["next_cursor"]})
        assert p2.status_code == 200
        p2_data = p2.json()
        assert [item["id"] for item in p2_data["items"]] == [a1["id"]]
        assert p2_data["next_cursor"] is None

        # Category filter
        sleep_list = anon.get("/api/v1/articles", params={"category": "睡眠与休息"})
        assert sleep_list.status_code == 200
        assert [x["id"] for x in sleep_list.json()["items"]] == [a3["id"], a1["id"]]

        # Keyword search hits published FTS/fallback and never leaks draft
        q_ok = anon.get("/api/v1/articles", params={"q": "散步"})
        assert q_ok.status_code == 200
        assert [x["id"] for x in q_ok.json()["items"]] == [a2["id"]]

        q_draft = anon.get("/api/v1/articles", params={"q": "不应公开检索词XYZ"})
        assert q_draft.status_code == 200
        assert q_draft.json()["items"] == []

        # Draft detail returns 404 publicly
        assert anon.get(f"/api/v1/articles/{draft_id}").status_code == 404


def test_t0502_editor_rbac_and_revision_tracking(app_instance, db_session: Session):
    """T-0502: Normal member and moderator-only get 403 on editor endpoints; editor creates/updates revisions."""
    with TestClient(app_instance) as anon:
        assert anon.get("/api/v1/editor/articles").status_code == 401

    with TestClient(app_instance) as mem_client:
        _, mem_csrf = _register_and_login(
            mem_client, db_session, account="mem_0502", nickname="普通用户", roles="member"
        )
        assert mem_client.get("/api/v1/editor/articles").status_code == 403
        assert (
            mem_client.post(
                "/api/v1/editor/articles",
                json={"title": "越权创建", "category": "日常健康", "summary": "s", "body": "b"},
                headers={"X-CSRF-Token": mem_csrf},
            ).status_code
            == 403
        )

    with TestClient(app_instance) as mod_client:
        _, mod_csrf = _register_and_login(
            mod_client, db_session, account="mod_0502", nickname="社区审核员", roles="member,moderator"
        )
        assert mod_client.get("/api/v1/editor/articles").status_code == 403
        assert (
            mod_client.post(
                "/api/v1/editor/articles",
                json={"title": "版主越权创建", "category": "日常健康", "summary": "s", "body": "b"},
                headers={"X-CSRF-Token": mod_csrf},
            ).status_code
            == 403
        )

    with TestClient(app_instance) as ed_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0502", nickname="编辑员", roles="member,editor"
        )
        created = ed_client.post(
            "/api/v1/editor/articles",
            json={
                "title": "心率与节律科普初稿",
                "category": "心脏基础知识",
                "summary": "初稿摘要",
                "body": "初稿内容版本一。",
            },
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert created.status_code == 201
        art = created.json()
        assert art["status"] == "draft"
        assert art["revision"] == 1

        patched = ed_client.patch(
            f"/api/v1/editor/articles/{art['id']}",
            json={
                "title": "心率与节律科普修订稿",
                "body": "修订后的版本二内容。",
                "sources": VALID_SOURCES,
                "review_record": VALID_REVIEW,
            },
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert patched.status_code == 200
        assert patched.json()["revision"] == 2
        assert patched.json()["title"] == "心率与节律科普修订稿"

        detail = ed_client.get(f"/api/v1/editor/articles/{art['id']}")
        assert detail.status_code == 200
        revs = detail.json()["revisions"]
        assert len(revs) == 2
        assert [r["revision"] for r in revs] == [1, 2]

        db_revs = db_session.scalars(
            select(ArticleRevision).where(ArticleRevision.article_id == art["id"])
        ).all()
        assert len(db_revs) == 2


def test_t0503_publish_requires_valid_sources_and_non_deceptive_review_record(
    app_instance, db_session: Session
):
    """T-0503: Publish fails with 422 if sources or review_record missing, unsafe URL schemes, or fake doctor review."""
    with TestClient(app_instance) as ed_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0503", nickname="内容编辑", roles="member,editor"
        )
        draft = ed_client.post(
            "/api/v1/editor/articles",
            json={
                "title": "减盐饮食科普",
                "category": "日常健康",
                "summary": "注意隐形盐摄入",
                "body": "成年人每日食盐建议不超过5克。",
            },
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert draft.status_code == 201
        art_id = draft.json()["id"]

        # Missing both sources and review_record -> 422
        r_missing_all = ed_client.post(
            f"/api/v1/editor/articles/{art_id}/publish",
            json={},
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert r_missing_all.status_code == 422

        # Missing review_record -> 422
        r_missing_rev = ed_client.post(
            f"/api/v1/editor/articles/{art_id}/publish",
            json={"sources": VALID_SOURCES},
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert r_missing_rev.status_code == 422

        # Missing sources -> 422
        r_missing_src = ed_client.post(
            f"/api/v1/editor/articles/{art_id}/publish",
            json={"sources": [], "review_record": VALID_REVIEW},
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert r_missing_src.status_code == 422

        # Unsafe URL schemes rejected with 422
        for bad_url in (
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
            "vbscript:msgbox(1)",
            "https://",
        ):
            r_bad_url = ed_client.post(
                f"/api/v1/editor/articles/{art_id}/publish",
                json={
                    "sources": [{"title": "恶意链接", "url": bad_url}],
                    "review_record": VALID_REVIEW,
                },
                headers={"X-CSRF-Token": ed_csrf},
            )
            assert r_bad_url.status_code == 422, f"Expected 422 for {bad_url}"

        # Deceptive review_type ("医生审核" / "临床专家审核") rejected with 422 (F-05)
        for bad_review_type in ("三甲主任医生审核", "临床专家审核"):
            r_bad_rev = ed_client.post(
                f"/api/v1/editor/articles/{art_id}/publish",
                json={
                    "sources": VALID_SOURCES,
                    "review_record": {
                        "reviewer": "某成员",
                        "review_type": bad_review_type,
                        "reviewed_at": "2026-11-26",
                    },
                },
                headers={"X-CSRF-Token": ed_csrf},
            )
            assert r_bad_rev.status_code == 422, f"Expected 422 for {bad_review_type}"

        # Valid sources + "课程内容审核" succeeds
        r_ok = ed_client.post(
            f"/api/v1/editor/articles/{art_id}/publish",
            json={"sources": VALID_SOURCES, "review_record": VALID_REVIEW},
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert r_ok.status_code == 200
        assert r_ok.json()["status"] == "published"
        assert r_ok.json()["published_at"] is not None


def test_t0504_article_detail_transparency_fields(app_instance, db_session: Session):
    """T-0504: Published article detail returns full transparency metadata including scope_note, sources, review_record."""
    with TestClient(app_instance) as ed_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0504", nickname="编辑0504", roles="member,editor"
        )
        pub = _create_and_publish_article(
            ed_client,
            ed_csrf,
            title="单导联心电记录的适用边界",
            category="设备与指标解读",
        )

    with TestClient(app_instance) as anon:
        res = anon.get(f"/api/v1/articles/{pub['id']}")
        assert res.status_code == 200
        data = res.json()
        required_keys = {
            "id",
            "title",
            "summary",
            "category",
            "body",
            "author_byline",
            "scope_note",
            "sources",
            "review_record",
            "revision",
            "is_demo",
            "published_at",
            "updated_at",
            "viewer_bookmarked",
        }
        assert required_keys.issubset(data.keys())
        assert data["viewer_bookmarked"] is False
        assert data["review_record"]["review_type"] == "课程内容审核"
        assert data["sources"][0]["url"].startswith("https://")
        assert "不作为" in data["scope_note"]


def test_t0505_article_bookmarks_idempotent_and_user_isolated(app_instance, db_session: Session):
    """T-0505: Bookmark & unbookmark published articles idempotently with per-user isolation."""
    with TestClient(app_instance) as ed_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0505", nickname="编辑0505", roles="member,editor"
        )
        pub = _create_and_publish_article(ed_client, ed_csrf, title="门诊沟通问题清单")
        draft = ed_client.post(
            "/api/v1/editor/articles",
            json={"title": "草稿不可收藏", "category": "就医与沟通", "summary": "s", "body": "b"},
            headers={"X-CSRF-Token": ed_csrf},
        ).json()

    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        _, csrf_alice = _register_and_login(c_alice, account="alice_0505", nickname="小禾")
        _, csrf_bob = _register_and_login(c_bob, account="bob_0505", nickname="远山")

        # Draft bookmark returns 404
        assert (
            c_alice.put(
                f"/api/v1/articles/{draft['id']}/bookmark",
                headers={"X-CSRF-Token": csrf_alice},
            ).status_code
            == 404
        )

        # Idempotent PUT bookmark
        b1 = c_alice.put(
            f"/api/v1/articles/{pub['id']}/bookmark",
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert b1.status_code == 200
        assert b1.json()["bookmarked"] is True

        b2 = c_alice.put(
            f"/api/v1/articles/{pub['id']}/bookmark",
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert b2.status_code == 200

        # Detail shows viewer_bookmarked=True for Alice, False for Bob
        assert c_alice.get(f"/api/v1/articles/{pub['id']}").json()["viewer_bookmarked"] is True
        assert c_bob.get(f"/api/v1/articles/{pub['id']}").json()["viewer_bookmarked"] is False

        alice_list = c_alice.get("/api/v1/me/article-bookmarks")
        assert alice_list.status_code == 200
        assert [x["id"] for x in alice_list.json()["items"]] == [pub["id"]]
        assert c_bob.get("/api/v1/me/article-bookmarks").json()["items"] == []

        # Idempotent DELETE bookmark
        d1 = c_alice.delete(
            f"/api/v1/articles/{pub['id']}/bookmark",
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert d1.status_code == 200
        assert d1.json()["bookmarked"] is False
        d2 = c_alice.delete(
            f"/api/v1/articles/{pub['id']}/bookmark",
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert d2.status_code == 200
        assert c_alice.get("/api/v1/me/article-bookmarks").json()["items"] == []


def test_t0506_unpublish_hides_article_from_public_search_bookmarks_and_history(
    app_instance, db_session: Session
):
    """T-0506: Unpublishing removes article from public list, FTS search, detail (404), bookmarks & reading history."""
    with TestClient(app_instance) as ed_client, TestClient(app_instance) as mem_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0506", nickname="编辑0506", roles="member,editor"
        )
        _, mem_csrf = _register_and_login(mem_client, account="mem_0506", nickname="读者")

        pub = _create_and_publish_article(
            ed_client,
            ed_csrf,
            title="咖啡因与心悸感受特刊独特词K99",
            category="日常健康",
            body="关注咖啡因敏感度与饮水习惯独特词K99。",
        )
        art_id = pub["id"]

        # Member bookmarks & reads it
        assert (
            mem_client.put(
                f"/api/v1/articles/{art_id}/bookmark", headers={"X-CSRF-Token": mem_csrf}
            ).status_code
            == 200
        )
        assert (
            mem_client.put(
                f"/api/v1/me/reading-history/{art_id}", headers={"X-CSRF-Token": mem_csrf}
            ).status_code
            == 200
        )

        # Editor unpublishes
        unpub = ed_client.post(
            f"/api/v1/editor/articles/{art_id}/unpublish",
            headers={"X-CSRF-Token": ed_csrf},
        )
        assert unpub.status_code == 200
        assert unpub.json()["status"] == "unpublished"

        # Public detail -> 404, public list & search -> empty, member bookmarks & history -> filtered out
        assert mem_client.get(f"/api/v1/articles/{art_id}").status_code == 404
        assert mem_client.get("/api/v1/articles", params={"q": "独特词K99"}).json()["items"] == []
        assert mem_client.get("/api/v1/me/article-bookmarks").json()["items"] == []
        assert mem_client.get("/api/v1/me/reading-history").json()["items"] == []

        # Editor can still manage it under status=unpublished
        ed_list = ed_client.get("/api/v1/editor/articles", params={"status": "unpublished"})
        assert ed_list.status_code == 200
        assert [x["id"] for x in ed_list.json()["items"]] == [art_id]


def test_t0507_reading_history_upsert_daily_log_and_isolated_clear(
    app_instance, db_session: Session, fake_clock: FakeClock
):
    """T-0507: Reading history upserts last_read_at + ReadingDailyLog, and DELETE clears only current user's history."""
    fake_clock.set(datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc))

    with TestClient(app_instance) as ed_client:
        _, ed_csrf = _register_and_login(
            ed_client, db_session, account="ed_0507", nickname="编辑0507", roles="member,editor"
        )
        a1 = _create_and_publish_article(ed_client, ed_csrf, title="科普文章一")
        a2 = _create_and_publish_article(ed_client, ed_csrf, title="科普文章二")
        draft = ed_client.post(
            "/api/v1/editor/articles",
            json={"title": "未发布草稿", "category": "日常健康", "summary": "s", "body": "b"},
            headers={"X-CSRF-Token": ed_csrf},
        ).json()

    with TestClient(app_instance) as c_u1, TestClient(app_instance) as c_u2:
        u1, csrf_u1 = _register_and_login(c_u1, account="reader_1", nickname="读者一")
        u2, csrf_u2 = _register_and_login(c_u2, account="reader_2", nickname="读者二")

        # Draft cannot be recorded in reading history
        assert (
            c_u1.put(
                f"/api/v1/me/reading-history/{draft['id']}",
                headers={"X-CSRF-Token": csrf_u1},
            ).status_code
            == 404
        )

        # User 1 reads a1, then later reads a2, then re-reads a1 (idempotent upsert updates order & daily log)
        assert (
            c_u1.put(
                f"/api/v1/me/reading-history/{a1['id']}",
                headers={"X-CSRF-Token": csrf_u1},
            ).status_code
            == 200
        )
        fake_clock.advance(minutes=5)
        assert (
            c_u1.put(
                f"/api/v1/me/reading-history/{a2['id']}",
                headers={"X-CSRF-Token": csrf_u1},
            ).status_code
            == 200
        )
        fake_clock.advance(minutes=5)
        assert (
            c_u1.put(
                f"/api/v1/me/reading-history/{a1['id']}",
                headers={"X-CSRF-Token": csrf_u1},
            ).status_code
            == 200
        )

        # User 2 reads a2
        assert (
            c_u2.put(
                f"/api/v1/me/reading-history/{a2['id']}",
                headers={"X-CSRF-Token": csrf_u2},
            ).status_code
            == 200
        )

        hist_u1 = c_u1.get("/api/v1/me/reading-history")
        assert hist_u1.status_code == 200
        assert [x["article_id"] for x in hist_u1.json()["items"]] == [a1["id"], a2["id"]]

        # Verify ReadingDailyLog created idempotently (exactly 1 row for u1 on 2026-11-25 Asia/Shanghai)
        db_session.expire_all()
        daily_logs = db_session.scalars(
            select(ReadingDailyLog).where(ReadingDailyLog.user_id == u1["id"])
        ).all()
        assert len(daily_logs) == 1
        assert str(daily_logs[0].local_date) == "2026-11-25"

        # User 1 clears reading history -> User 1 empty, User 2 untouched!
        del_res = c_u1.delete("/api/v1/me/reading-history", headers={"X-CSRF-Token": csrf_u1})
        assert del_res.status_code == 200
        assert c_u1.get("/api/v1/me/reading-history").json()["items"] == []

        hist_u2 = c_u2.get("/api/v1/me/reading-history")
        assert hist_u2.status_code == 200
        assert [x["article_id"] for x in hist_u2.json()["items"]] == [a2["id"]]

        db_session.expire_all()
        rem_u2 = db_session.scalars(
            select(ReadingHistory).where(ReadingHistory.user_id == u2["id"])
        ).all()
        assert len(rem_u2) == 1
