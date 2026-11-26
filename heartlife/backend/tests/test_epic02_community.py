from __future__ import annotations

from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FakeClock
from app.db.models import (
    Article,
    Comment,
    JournalEntry,
    ModerationAction,
    Notification,
    Plan,
    Post,
    Report,
    User,
)

EXPECTED_CATEGORIES = [
    "日常健康",
    "运动与习惯",
    "睡眠与休息",
    "心脏健康科普交流",
    "设备使用经验",
]

EXPECTED_SAFETY_NOTICE = (
    "社区交流不提供个体化诊疗或用药建议；如遇急性不适请立即拨打急救电话或前往正规医院就诊"
)


def _register_and_login(
    client: TestClient,
    account: str,
    nickname: str,
    password: str = "SafePass123!",
) -> tuple[dict, str]:
    reg = client.post(
        "/api/v1/auth/register",
        json={"account": account, "password": password, "nickname": nickname},
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["user"], body["csrf_token"]


def _grant_role(db_session: Session, user_id: str, roles: str) -> None:
    user = db_session.scalar(select(User).where(User.id == user_id))
    assert user is not None
    user.roles = roles
    db_session.commit()


def test_t0201_categories_and_create_post_author_binding_and_safety_notice(
    app_instance,
):
    """T-0201: Fixed 5 categories, post author strictly bound to current_user, tag dedup & safety notice."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        alice, csrf_alice = _register_and_login(c_alice, "alice0201", "林晓禾")
        bob, _ = _register_and_login(c_bob, "bob0201", "陈远山")

        cat_res = c_alice.get("/api/v1/community/categories")
        assert cat_res.status_code == 200
        assert cat_res.json()["categories"] == EXPECTED_CATEGORIES

        # Attempt to forge author_id must be rejected by extra="forbid"
        forged = c_alice.post(
            "/api/v1/posts",
            json={
                "title": "散步打卡第一周",
                "body": "每天晚饭后散步二十分钟，睡眠踏实很多。",
                "category": "运动与习惯",
                "tags": ["散步", "微习惯", "散步"],
                "author_id": bob["id"],
            },
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert forged.status_code == 422

        # Valid normal post: no safety notice, tags deduplicated in order
        ok = c_alice.post(
            "/api/v1/posts",
            json={
                "title": "  散步打卡第一周  ",
                "body": "  每天晚饭后散步二十分钟，睡眠踏实很多。  ",
                "category": "运动与习惯",
                "tags": [" 散步 ", "微习惯", "散步"],
            },
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert ok.status_code == 201, ok.text
        post_data = ok.json()
        assert post_data["author"]["id"] == alice["id"]
        assert post_data["author"]["nickname"] == "林晓禾"
        assert post_data["title"] == "散步打卡第一周"
        assert post_data["body"] == "每天晚饭后散步二十分钟，睡眠踏实很多。"
        assert post_data["tags"] == ["散步", "微习惯"]
        assert post_data["safety_notice"] is None
        assert post_data["version"] == 1
        assert post_data["like_count"] == 0
        assert post_data["comment_count"] == 0

        # Post containing emergency / prescription keyword triggers safety_notice
        warn = c_alice.post(
            "/api/v1/posts",
            json={
                "title": "请问心率快应该开什么药？吃几毫克？",
                "body": "昨晚有点胸痛，想问问大家能不能自己停药。",
                "category": "日常健康",
                "tags": ["求助"],
            },
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert warn.status_code == 201
        assert warn.json()["safety_notice"] == EXPECTED_SAFETY_NOTICE


def test_t0202_invalid_post_payloads_auth_and_csrf_rejected(app_instance):
    """T-0202: Reject invalid title/body/category/tags, unauthenticated, and missing CSRF."""
    with TestClient(app_instance) as anon:
        assert (
            anon.post(
                "/api/v1/posts",
                json={"title": "标题", "body": "内容", "category": "日常健康"},
            ).status_code
            == 401
        )

    with TestClient(app_instance) as c:
        _, csrf = _register_and_login(c, "alice0202", "小禾")

        # Missing CSRF -> 403
        assert (
            c.post(
                "/api/v1/posts",
                json={"title": "标题", "body": "内容", "category": "日常健康"},
            ).status_code
            == 403
        )

        invalid_payloads = [
            {"title": "   ", "body": "有效正文", "category": "日常健康"},
            {"title": "口" * 81, "body": "有效正文", "category": "日常健康"},
            {"title": "有效标题", "body": "   ", "category": "日常健康"},
            {"title": "有效标题", "body": "文" * 3001, "category": "日常健康"},
            {"title": "有效标题", "body": "有效正文", "category": "未授权分类"},
            {
                "title": "有效标题",
                "body": "有效正文",
                "category": "日常健康",
                "tags": ["t1", "t2", "t3", "t4", "t5", "t6"],
            },
            {
                "title": "有效标题",
                "body": "有效正文",
                "category": "日常健康",
                "tags": ["   "],
            },
            {
                "title": "有效标题",
                "body": "有效正文",
                "category": "日常健康",
                "tags": ["标" * 21],
            },
        ]
        for bad in invalid_payloads:
            res = c.post("/api/v1/posts", json=bad, headers={"X-CSRF-Token": csrf})
            assert res.status_code == 422, f"Expected 422 for {bad}, got {res.status_code}: {res.text}"


def test_t0203_cursor_pagination_stable_under_identical_timestamps(
    app_instance,
    fake_clock: FakeClock,
):
    """T-0203: Stable (created_at DESC, id DESC) cursor pagination with identical timestamps."""
    with TestClient(app_instance) as c:
        _, csrf = _register_and_login(c, "pager0203", "分页用户")

        # Create 5 posts at the EXACT same FakeClock timestamp + 1 newer post
        same_ts_ids: list[str] = []
        for idx in range(5):
            r = c.post(
                "/api/v1/posts",
                json={
                    "title": f"同时间戳帖子-{idx}",
                    "body": f"正文内容-{idx}",
                    "category": "日常健康",
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert r.status_code == 201
            same_ts_ids.append(r.json()["id"])

        fake_clock.advance(seconds=30)
        r_newest = c.post(
            "/api/v1/posts",
            json={"title": "最新帖子", "body": "最新正文", "category": "睡眠与休息"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r_newest.status_code == 201
        newest_id = r_newest.json()["id"]

        expected_order = [newest_id] + sorted(same_ts_ids, reverse=True)

        collected_ids: list[str] = []
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, object] = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            page = c.get("/api/v1/posts", params=params)
            assert page.status_code == 200, page.text
            data = page.json()
            collected_ids.extend(item["id"] for item in data["items"])
            cursor = data["next_cursor"]
            if cursor is None:
                break

        assert collected_ids == expected_order
        assert len(set(collected_ids)) == 6

        # Malformed cursor rejected with 422
        assert c.get("/api/v1/posts", params={"cursor": "not-a-valid-cursor"}).status_code == 422


def test_t0204_filter_by_category_tag_and_search_query(app_instance):
    """T-0204: Filter posts by category, tag, and case-insensitive q across title/body/tags without duplicates."""
    with TestClient(app_instance) as c:
        _, csrf = _register_and_login(c, "search0204", "检索员")

        p1 = c.post(
            "/api/v1/posts",
            json={
                "title": "晨间 HRV 观察笔记",
                "body": "早起静坐五分钟再做记录更平稳。",
                "category": "设备使用经验",
                "tags": ["HRV记录", "HRV日常"],
            },
            headers={"X-CSRF-Token": csrf},
        ).json()
        p2 = c.post(
            "/api/v1/posts",
            json={
                "title": "十点半熄灯打卡",
                "body": "减少睡前刷手机，助眠效果明显。",
                "category": "睡眠与休息",
                "tags": ["早睡", "SleepRoutine"],
            },
            headers={"X-CSRF-Token": csrf},
        ).json()

        by_cat = c.get("/api/v1/posts", params={"category": "睡眠与休息"}).json()["items"]
        assert [i["id"] for i in by_cat] == [p2["id"]]

        by_tag = c.get("/api/v1/posts", params={"tag": "HRV记录"}).json()["items"]
        assert [i["id"] for i in by_tag] == [p1["id"]]

        # Case-insensitive search matching multiple tags on p1 must not duplicate p1
        by_q_hrv = c.get("/api/v1/posts", params={"q": "hrv"}).json()["items"]
        assert [i["id"] for i in by_q_hrv] == [p1["id"]]

        # Case-insensitive search matching English tag on p2
        by_q_sleep = c.get("/api/v1/posts", params={"q": "sleeproutine"}).json()["items"]
        assert [i["id"] for i in by_q_sleep] == [p2["id"]]


def test_t0205_author_only_edit_and_delete_with_version_increment(app_instance):
    """T-0205: Only post author can PATCH or DELETE; PATCH bumps version; DELETE removes from feeds."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        _, csrf_alice = _register_and_login(c_alice, "alice0205", "作者甲")
        _, csrf_bob = _register_and_login(c_bob, "bob0205", "路人乙")

        created = c_alice.post(
            "/api/v1/posts",
            json={
                "title": "初始标题",
                "body": "初始正文",
                "category": "日常健康",
                "tags": ["旧标签"],
            },
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = created["id"]

        # Non-author cannot edit or delete
        assert (
            c_bob.patch(
                f"/api/v1/posts/{pid}",
                json={"title": "篡改标题"},
                headers={"X-CSRF-Token": csrf_bob},
            ).status_code
            == 403
        )
        assert (
            c_bob.delete(
                f"/api/v1/posts/{pid}",
                headers={"X-CSRF-Token": csrf_bob},
            ).status_code
            == 403
        )
        # Missing post -> 404
        assert (
            c_alice.patch(
                "/api/v1/posts/nonexistent_id",
                json={"title": "不存在"},
                headers={"X-CSRF-Token": csrf_alice},
            ).status_code
            == 404
        )

        # Author edits post -> version increments to 2
        patched = c_alice.patch(
            f"/api/v1/posts/{pid}",
            json={
                "title": "更新后的标题",
                "body": "更新后的正文",
                "category": "运动与习惯",
                "tags": ["新标签A", "新标签B", "新标签A"],
            },
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert patched.status_code == 200
        pdata = patched.json()
        assert pdata["version"] == 2
        assert pdata["title"] == "更新后的标题"
        assert pdata["category"] == "运动与习惯"
        assert pdata["tags"] == ["新标签A", "新标签B"]

        # Author deletes post -> soft deleted and excluded everywhere
        deleted = c_alice.delete(f"/api/v1/posts/{pid}", headers={"X-CSRF-Token": csrf_alice})
        assert deleted.status_code == 200
        assert c_alice.get(f"/api/v1/posts/{pid}").status_code == 404
        assert c_alice.get("/api/v1/posts").json()["items"] == []
        assert c_alice.get("/api/v1/me/posts").json()["items"] == []


def test_t0206_xss_plain_text_roundtrip_without_execution(app_instance):
    """T-0206: Script/HTML payloads round-trip safely as plain JSON strings."""
    xss_title = "<script>alert(1)</script> 睡眠记录"
    xss_body = '今晚 22:30 睡 <img src=x onerror="alert(2)"> & 保持安静'
    xss_comment = "<svg onload=alert(3)>同感</svg>"

    with TestClient(app_instance) as c:
        _, csrf = _register_and_login(c, "xss0206", "安全测试")
        post_res = c.post(
            "/api/v1/posts",
            json={
                "title": xss_title,
                "body": xss_body,
                "category": "睡眠与休息",
                "tags": ["<b>标签</b>"],
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert post_res.status_code == 201
        assert "application/json" in post_res.headers["content-type"]
        post_json = post_res.json()
        assert post_json["title"] == xss_title
        assert post_json["body"] == xss_body
        assert post_json["tags"] == ["<b>标签</b>"]

        cm_res = c.post(
            f"/api/v1/posts/{post_json['id']}/comments",
            json={"body": xss_comment},
            headers={"X-CSRF-Token": csrf},
        )
        assert cm_res.status_code == 201
        assert cm_res.json()["body"] == xss_comment


def test_t0207_idempotent_post_likes_and_viewer_state(app_instance):
    """T-0207: Repeated PUT/DELETE on post like is idempotent and never goes negative."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        _, csrf_alice = _register_and_login(c_alice, "alice0207", "发帖人")
        _, csrf_bob = _register_and_login(c_bob, "bob0207", "点赞人")

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "慢跑十分钟", "body": "循序渐进不勉强", "category": "运动与习惯"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        r1 = c_bob.put(f"/api/v1/posts/{pid}/like", headers={"X-CSRF-Token": csrf_bob})
        r2 = c_bob.put(f"/api/v1/posts/{pid}/like", headers={"X-CSRF-Token": csrf_bob})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == {"liked": True, "like_count": 1}
        assert r2.json() == {"liked": True, "like_count": 1}

        bob_view = c_bob.get(f"/api/v1/posts/{pid}").json()
        alice_view = c_alice.get(f"/api/v1/posts/{pid}").json()
        assert bob_view["viewer_liked"] is True
        assert bob_view["like_count"] == 1
        assert alice_view["viewer_liked"] is False
        assert alice_view["like_count"] == 1

        d1 = c_bob.delete(f"/api/v1/posts/{pid}/like", headers={"X-CSRF-Token": csrf_bob})
        d2 = c_bob.delete(f"/api/v1/posts/{pid}/like", headers={"X-CSRF-Token": csrf_bob})
        assert d1.status_code == 200
        assert d2.status_code == 200
        assert d1.json() == {"liked": False, "like_count": 0}
        assert d2.json() == {"liked": False, "like_count": 0}


def test_t0208_bookmarks_private_idempotent_and_visibility_filtered(
    app_instance,
    db_session: Session,
):
    """T-0208: Bookmarks support post & published article, are idempotent and private to owner."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        alice, csrf_alice = _register_and_login(c_alice, "alice0208", "收藏者甲")
        _, csrf_bob = _register_and_login(c_bob, "bob0208", "用户乙")

        post = c_bob.post(
            "/api/v1/posts",
            json={"title": "科学饮水习惯", "body": "少量多次补充水分", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_bob},
        ).json()
        pid = post["id"]

        # Seed one published article and one draft article directly in DB
        now = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
        pub_art = Article(
            slug="pub-art-0208",
            editor_id=alice["id"],
            status="published",
            title="公开科普文章",
            summary="摘要",
            category="日常健康",
            body="科普正文",
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        draft_art = Article(
            slug="draft-art-0208",
            editor_id=alice["id"],
            status="draft",
            title="未发布草稿",
            summary="草稿摘要",
            category="日常健康",
            body="草稿正文",
            created_at=now,
            updated_at=now,
        )
        db_session.add_all([pub_art, draft_art])
        db_session.commit()
        pub_art_id = pub_art.id
        draft_art_id = draft_art.id

        # Invalid target_type -> 422; draft article -> 404
        assert (
            c_alice.put(
                f"/api/v1/bookmarks/unknown/{pid}",
                headers={"X-CSRF-Token": csrf_alice},
            ).status_code
            == 422
        )
        assert (
            c_alice.put(
                f"/api/v1/bookmarks/article/{draft_art_id}",
                headers={"X-CSRF-Token": csrf_alice},
            ).status_code
            == 404
        )

        # Idempotent PUT for post and published article
        for _ in range(2):
            res_p = c_alice.put(f"/api/v1/bookmarks/post/{pid}", headers={"X-CSRF-Token": csrf_alice})
            assert res_p.status_code == 200
            assert res_p.json()["bookmarked"] is True

            res_a = c_alice.put(
                f"/api/v1/bookmarks/article/{pub_art_id}",
                headers={"X-CSRF-Token": csrf_alice},
            )
            assert res_a.status_code == 200
            assert res_a.json()["bookmarked"] is True

        assert c_alice.get(f"/api/v1/posts/{pid}").json()["viewer_bookmarked"] is True
        assert c_bob.get(f"/api/v1/posts/{pid}").json()["viewer_bookmarked"] is False

        # Private to Alice: Bob sees empty bookmarks
        alice_bms = c_alice.get("/api/v1/me/bookmarks").json()["items"]
        assert len(alice_bms) == 2
        assert len(c_alice.get("/api/v1/me/bookmarks", params={"target_type": "post"}).json()["items"]) == 1
        assert len(c_alice.get("/api/v1/me/bookmarks", params={"target_type": "article"}).json()["items"]) == 1
        assert c_bob.get("/api/v1/me/bookmarks").json()["items"] == []

        # Idempotent DELETE
        assert (
            c_alice.delete(f"/api/v1/bookmarks/post/{pid}", headers={"X-CSRF-Token": csrf_alice}).status_code
            == 200
        )
        assert (
            c_alice.delete(f"/api/v1/bookmarks/post/{pid}", headers={"X-CSRF-Token": csrf_alice}).status_code
            == 200
        )
        assert len(c_alice.get("/api/v1/me/bookmarks").json()["items"]) == 1


def test_t0209_comments_single_reply_depth_and_author_delete(app_instance):
    """T-0209: Allow 1-level replies; reject 2nd-level reply with 422 MAX_REPLY_DEPTH; author-only delete."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        _, csrf_alice = _register_and_login(c_alice, "alice0209", "楼主")
        _, csrf_bob = _register_and_login(c_bob, "bob0209", "层主")

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "作息讨论帖", "body": "欢迎交流经验", "category": "睡眠与休息"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        top = c_bob.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "一层评论：我也觉得固定起床时间很有用"},
            headers={"X-CSRF-Token": csrf_bob},
        )
        assert top.status_code == 201
        top_id = top.json()["id"]

        reply1 = c_alice.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "一层回复：谢谢分享！", "parent_id": top_id},
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert reply1.status_code == 201
        reply1_id = reply1.json()["id"]

        # Replying to a reply (depth 2) must fail with 422 MAX_REPLY_DEPTH
        depth2 = c_bob.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "二层嵌套回复应被拒绝", "parent_id": reply1_id},
            headers={"X-CSRF-Token": csrf_bob},
        )
        assert depth2.status_code == 422
        assert depth2.json()["error"]["code"] == "MAX_REPLY_DEPTH"

        comments_list = c_alice.get(f"/api/v1/posts/{pid}/comments").json()["items"]
        assert [c["id"] for c in comments_list] == [top_id, reply1_id]
        assert c_alice.get(f"/api/v1/posts/{pid}").json()["comment_count"] == 2

        # Non-author cannot delete Bob's comment
        assert (
            c_alice.delete(f"/api/v1/comments/{top_id}", headers={"X-CSRF-Token": csrf_alice}).status_code
            == 403
        )

        # Author deletes reply1 -> count drops to 1
        assert (
            c_alice.delete(f"/api/v1/comments/{reply1_id}", headers={"X-CSRF-Token": csrf_alice}).status_code
            == 200
        )
        assert [c["id"] for c in c_alice.get(f"/api/v1/posts/{pid}/comments").json()["items"]] == [top_id]
        assert c_alice.get(f"/api/v1/posts/{pid}").json()["comment_count"] == 1


def test_t0210_comment_request_id_idempotency_and_notifications(
    app_instance,
    db_session: Session,
):
    """T-0210: Comment request_id prevents duplicate comments & notifications; self-comment suppressed."""
    with (
        TestClient(app_instance) as c_alice,
        TestClient(app_instance) as c_bob,
        TestClient(app_instance) as c_carol,
    ):
        alice, csrf_alice = _register_and_login(c_alice, "alice0210", "小禾")
        bob, csrf_bob = _register_and_login(c_bob, "bob0210", "远山")
        _, csrf_carol = _register_and_login(c_carol, "carol0210", "清风")

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "晚餐少盐经验", "body": "多用天然香料调味", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        # Self-comment creates no notification
        self_cm = c_alice.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "补充一点：柠檬汁很好用", "request_id": "req-self-1"},
            headers={"X-CSRF-Token": csrf_alice},
        )
        assert self_cm.status_code == 201

        # Bob comments twice with same request_id -> only 1 comment & 1 notification for Alice
        b1 = c_bob.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "学到了，今晚试试！", "request_id": "req-bob-1"},
            headers={"X-CSRF-Token": csrf_bob},
        )
        b2 = c_bob.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "学到了，今晚试试！", "request_id": "req-bob-1"},
            headers={"X-CSRF-Token": csrf_bob},
        )
        assert b1.status_code in (200, 201)
        assert b2.status_code in (200, 201)
        assert b1.json()["id"] == b2.json()["id"]
        bob_cm_id = b1.json()["id"]

        # Carol replies to Bob's comment twice with same request_id -> 1 reply & 1 notification for Bob
        r1 = c_carol.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "番茄炖菜也很提味", "parent_id": bob_cm_id, "request_id": "req-carol-1"},
            headers={"X-CSRF-Token": csrf_carol},
        )
        r2 = c_carol.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "番茄炖菜也很提味", "parent_id": bob_cm_id, "request_id": "req-carol-1"},
            headers={"X-CSRF-Token": csrf_carol},
        )
        assert r1.json()["id"] == r2.json()["id"]

        db_session.expire_all()
        total_comments = db_session.scalar(select(func.count()).select_from(Comment).where(Comment.post_id == pid))
        assert total_comments == 3

        alice_notifs = db_session.scalars(
            select(Notification).where(Notification.recipient_id == alice["id"])
        ).all()
        assert len(alice_notifs) == 1
        assert alice_notifs[0].type == "post_comment"

        bob_notifs = db_session.scalars(
            select(Notification).where(Notification.recipient_id == bob["id"])
        ).all()
        assert len(bob_notifs) == 1
        assert bob_notifs[0].type == "comment_reply"


def test_t0211_hidden_post_blocked_from_public_reads_and_interactions_but_visible_in_me_posts(
    app_instance,
    db_session: Session,
):
    """T-0211: Hidden post returns 404 for detail/like/bookmark/comments, yet shows status in GET /me/posts."""
    with (
        TestClient(app_instance) as c_alice,
        TestClient(app_instance) as c_bob,
        TestClient(app_instance) as c_mod,
    ):
        _, csrf_alice = _register_and_login(c_alice, "alice0211", "发帖人")
        _, csrf_bob = _register_and_login(c_bob, "bob0211", "普通读者")
        mod_user, csrf_mod = _register_and_login(c_mod, "mod0211", "审核员")
        _grant_role(db_session, mod_user["id"], "member,moderator")

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "待隐藏帖子", "body": "包含违规广告链接", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        # Bob bookmarks before hide
        assert c_bob.put(f"/api/v1/bookmarks/post/{pid}", headers={"X-CSRF-Token": csrf_bob}).status_code == 200

        # Moderator hides the post
        hide_res = c_mod.post(
            f"/api/v1/moderation/content/post/{pid}/hide",
            json={"reason": "涉嫌商业推广链接"},
            headers={"X-CSRF-Token": csrf_mod},
        )
        assert hide_res.status_code == 200

        # Public endpoints all return 404 and feed/bookmarks exclude it
        assert c_bob.get(f"/api/v1/posts/{pid}").status_code == 404
        assert c_alice.get(f"/api/v1/posts/{pid}").status_code == 404
        assert c_bob.get("/api/v1/posts").json()["items"] == []
        assert c_bob.get("/api/v1/me/bookmarks").json()["items"] == []
        assert c_bob.put(f"/api/v1/posts/{pid}/like", headers={"X-CSRF-Token": csrf_bob}).status_code == 404
        assert c_bob.put(f"/api/v1/bookmarks/post/{pid}", headers={"X-CSRF-Token": csrf_bob}).status_code == 404
        assert c_bob.get(f"/api/v1/posts/{pid}/comments").status_code == 404
        assert (
            c_bob.post(
                f"/api/v1/posts/{pid}/comments",
                json={"body": "不能评论隐藏帖"},
                headers={"X-CSRF-Token": csrf_bob},
            ).status_code
            == 404
        )

        # Author can still inspect status & moderation_reason in /me/posts
        my_posts = c_alice.get("/api/v1/me/posts").json()["items"]
        assert len(my_posts) == 1
        assert my_posts[0]["id"] == pid
        assert my_posts[0]["status"] == "hidden"
        assert my_posts[0]["moderation_reason"] == "涉嫌商业推广链接"


def test_t0212_report_submission_and_pending_deduplication(
    app_instance,
    db_session: Session,
):
    """T-0212: Submitting duplicate pending report for same target by same user is idempotent."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob:
        _, csrf_alice = _register_and_login(c_alice, "alice0212", "作者")
        _, csrf_bob = _register_and_login(c_bob, "bob0212", "举报人")

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "疑似偏方分享", "body": "某种保健品包治百病", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        # Nonexistent target -> 404
        assert (
            c_bob.post(
                "/api/v1/reports",
                json={"target_type": "post", "target_id": "missing_post", "reason": "spam"},
                headers={"X-CSRF-Token": csrf_bob},
            ).status_code
            == 404
        )

        rep1 = c_bob.post(
            "/api/v1/reports",
            json={
                "target_type": "post",
                "target_id": pid,
                "reason": "misleading_medical",
                "detail": "宣称包治百病误导他人",
            },
            headers={"X-CSRF-Token": csrf_bob},
        )
        rep2 = c_bob.post(
            "/api/v1/reports",
            json={
                "target_type": "post",
                "target_id": pid,
                "reason": "spam",
                "detail": "重复提交同目标举报",
            },
            headers={"X-CSRF-Token": csrf_bob},
        )
        assert rep1.status_code in (200, 201)
        assert rep2.status_code in (200, 201)
        assert rep1.json()["id"] == rep2.json()["id"]

        db_session.expire_all()
        count = db_session.scalar(select(func.count()).select_from(Report).where(Report.target_id == pid))
        assert count == 1


def test_t0213_moderator_rbac_privacy_boundary_and_resolve_report(
    app_instance,
    db_session: Session,
):
    """T-0213: Normal member gets 403 on moderation; moderator sees public text only (no journals/plans) and resolves."""
    with (
        TestClient(app_instance) as c_alice,
        TestClient(app_instance) as c_bob,
        TestClient(app_instance) as c_mod,
    ):
        alice, csrf_alice = _register_and_login(c_alice, "alice0213", "被举报作者")
        _, csrf_bob = _register_and_login(c_bob, "bob0213", "普通会员")
        mod_user, csrf_mod = _register_and_login(c_mod, "mod0213", "专职审核员")
        _grant_role(db_session, mod_user["id"], "member,moderator")

        # Seed Alice's private journal and private plan to verify strict isolation
        now = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
        db_session.add(
            JournalEntry(
                user_id=alice["id"],
                local_date=now.date(),
                sleep_minutes=420,
                note="私密日记绝密内容_PRIVATE_JOURNAL_SECRET",
                created_at=now,
                updated_at=now,
            )
        )
        db_session.add(
            Plan(
                owner_id=alice["id"],
                title="私密习惯计划_PRIVATE_PLAN_SECRET",
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "公开帖子标题", "body": "公开帖子内容含疑似替人开处方", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        rep = c_bob.post(
            "/api/v1/reports",
            json={"target_type": "post", "target_id": pid, "reason": "misleading_medical"},
            headers={"X-CSRF-Token": csrf_bob},
        ).json()

        # Normal user denied moderation endpoints
        assert c_bob.get("/api/v1/moderation/reports").status_code == 403
        assert (
            c_bob.post(
                f"/api/v1/moderation/reports/{rep['id']}/resolve",
                json={"decision": "actioned", "hide_target": True, "reason": "越权"},
                headers={"X-CSRF-Token": csrf_bob},
            ).status_code
            == 403
        )

        # Moderator inspects pending queue -> never leaks private journal/plan secrets
        queue_res = c_mod.get("/api/v1/moderation/reports", params={"status": "pending"})
        assert queue_res.status_code == 200
        raw_queue_text = queue_res.text
        assert "PRIVATE_JOURNAL_SECRET" not in raw_queue_text
        assert "PRIVATE_PLAN_SECRET" not in raw_queue_text
        queue_items = queue_res.json()["items"]
        assert len(queue_items) == 1
        assert queue_items[0]["target_preview"]["title"] == "公开帖子标题"

        # Moderator resolves report as actioned + hide_target
        res_mod = c_mod.post(
            f"/api/v1/moderation/reports/{rep['id']}/resolve",
            json={"decision": "actioned", "hide_target": True, "reason": "请勿在社区提供个体化处方建议"},
            headers={"X-CSRF-Token": csrf_mod},
        )
        assert res_mod.status_code == 200
        assert c_bob.get(f"/api/v1/posts/{pid}").status_code == 404

        db_session.expire_all()
        notifs = db_session.scalars(
            select(Notification).where(
                Notification.recipient_id == alice["id"],
                Notification.type == "moderation_result",
            )
        ).all()
        assert len(notifs) == 1
        assert "请勿在社区提供个体化处方建议" in notifs[0].summary


def test_t0214_moderator_restore_and_immutable_audit_history(
    app_instance,
    db_session: Session,
):
    """T-0214: Restoring hidden content makes it visible again and preserves prior ModerationAction history."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_mod:
        _, csrf_alice = _register_and_login(c_alice, "alice0214", "作者")
        mod_user, csrf_mod = _register_and_login(c_mod, "mod0214", "审核员")
        _grant_role(db_session, mod_user["id"], "member,moderator")

        post = c_alice.post(
            "/api/v1/posts",
            json={"title": "正常科普心得", "body": "记录静息心率的小技巧", "category": "心脏健康科普交流"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        pid = post["id"]

        # Create a top-level comment and a reply, then hide the top-level comment -> both omitted from public list
        top_cm = c_alice.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "一层评论"},
            headers={"X-CSRF-Token": csrf_alice},
        ).json()
        c_alice.post(
            f"/api/v1/posts/{pid}/comments",
            json={"body": "一层评论下的回复", "parent_id": top_cm["id"]},
            headers={"X-CSRF-Token": csrf_alice},
        )
        c_mod.post(
            f"/api/v1/moderation/content/comment/{top_cm['id']}/hide",
            json={"reason": "测试隐藏父评论"},
            headers={"X-CSRF-Token": csrf_mod},
        )
        assert c_alice.get(f"/api/v1/posts/{pid}/comments").json()["items"] == []
        c_mod.post(
            f"/api/v1/moderation/content/comment/{top_cm['id']}/restore",
            json={"reason": "恢复父评论"},
            headers={"X-CSRF-Token": csrf_mod},
        )
        assert len(c_alice.get(f"/api/v1/posts/{pid}/comments").json()["items"]) == 2

        # Hide first
        h = c_mod.post(
            f"/api/v1/moderation/content/post/{pid}/hide",
            json={"reason": "误判隐藏"},
            headers={"X-CSRF-Token": csrf_mod},
        )
        assert h.status_code == 200
        assert c_alice.get(f"/api/v1/posts/{pid}").status_code == 404

        # Restore
        r = c_mod.post(
            f"/api/v1/moderation/content/post/{pid}/restore",
            json={"reason": "复核无违规予以恢复"},
            headers={"X-CSRF-Token": csrf_mod},
        )
        assert r.status_code == 200
        restored_detail = c_alice.get(f"/api/v1/posts/{pid}")
        assert restored_detail.status_code == 200
        assert restored_detail.json()["moderation_reason"] is None

        # Audit log preserves BOTH hide and restore actions
        audit_res = c_mod.get("/api/v1/moderation/actions")
        assert audit_res.status_code == 200
        actions_for_post = [a for a in audit_res.json()["items"] if a["target_id"] == pid]
        assert {a["action"] for a in actions_for_post} == {"hide", "restore"}
        assert len(actions_for_post) == 2

        db_session.expire_all()
        db_actions = db_session.scalars(
            select(ModerationAction).where(ModerationAction.target_id == pid)
        ).all()
        assert len(db_actions) == 2


def test_t0215_user_blocking_filters_posts_comments_and_bookmarks(app_instance):
    """T-0215: Blocking a user hides their posts and comments from blocker, cannot self-block, idempotent."""
    with (
        TestClient(app_instance) as c_alice,
        TestClient(app_instance) as c_bob,
        TestClient(app_instance) as c_carol,
    ):
        alice, csrf_alice = _register_and_login(c_alice, "alice0215", "屏蔽者")
        bob, csrf_bob = _register_and_login(c_bob, "bob0215", "被屏蔽者")
        _, csrf_carol = _register_and_login(c_carol, "carol0215", "第三方")

        bob_post = c_bob.post(
            "/api/v1/posts",
            json={"title": "Bob的帖子", "body": "Bob的正文", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_bob},
        ).json()
        carol_post = c_carol.post(
            "/api/v1/posts",
            json={"title": "Carol的帖子", "body": "Carol的正文", "category": "日常健康"},
            headers={"X-CSRF-Token": csrf_carol},
        ).json()

        bob_cm = c_bob.post(
            f"/api/v1/posts/{carol_post['id']}/comments",
            json={"body": "Bob在Carol帖下的评论"},
            headers={"X-CSRF-Token": csrf_bob},
        ).json()

        # Alice bookmarks Bob's post before blocking
        c_alice.put(f"/api/v1/bookmarks/post/{bob_post['id']}", headers={"X-CSRF-Token": csrf_alice})

        # Self-block rejected with 422
        assert (
            c_alice.put(f"/api/v1/me/blocks/{alice['id']}", headers={"X-CSRF-Token": csrf_alice}).status_code
            == 422
        )

        # Idempotent block Bob
        for _ in range(2):
            blk = c_alice.put(f"/api/v1/me/blocks/{bob['id']}", headers={"X-CSRF-Token": csrf_alice})
            assert blk.status_code == 200
            assert blk.json()["blocked"] is True

        blocks_list = c_alice.get("/api/v1/me/blocks").json()["items"]
        assert [b["blocked_id"] for b in blocks_list] == [bob["id"]]

        # Alice no longer sees Bob's post in feed, detail (404), bookmarks, or Bob's comments
        feed_ids = [p["id"] for p in c_alice.get("/api/v1/posts").json()["items"]]
        assert bob_post["id"] not in feed_ids
        assert carol_post["id"] in feed_ids
        assert c_alice.get(f"/api/v1/posts/{bob_post['id']}").status_code == 404
        assert c_alice.get("/api/v1/me/bookmarks").json()["items"] == []
        carol_comments_for_alice = c_alice.get(f"/api/v1/posts/{carol_post['id']}/comments").json()["items"]
        assert all(cm["id"] != bob_cm["id"] for cm in carol_comments_for_alice)

        # Carol (who did not block Bob) still sees Bob's post and comment
        assert c_carol.get(f"/api/v1/posts/{bob_post['id']}").status_code == 200
        assert len(c_carol.get(f"/api/v1/posts/{carol_post['id']}/comments").json()["items"]) == 1

        # Idempotent unblock restores visibility for Alice
        for _ in range(2):
            unblk = c_alice.delete(f"/api/v1/me/blocks/{bob['id']}", headers={"X-CSRF-Token": csrf_alice})
            assert unblk.status_code == 200
            assert unblk.json()["blocked"] is False
        assert c_alice.get(f"/api/v1/posts/{bob_post['id']}").status_code == 200


def test_t0806_topic_category_follows_and_followed_only_feed_never_uses_journal(
    app_instance,
    db_session: Session,
):
    """T-0806: Follow/unfollow community categories idempotently; followed_only filters strictly by TopicFollow."""
    with TestClient(app_instance) as c_alice, TestClient(app_instance) as c_bob, TestClient(app_instance) as anon:
        alice, csrf_alice = _register_and_login(c_alice, "alice0806", "关注者")
        _, csrf_bob = _register_and_login(c_bob, "bob0806", "作者")

        # Seed a sleep JournalEntry for Alice to prove followed_only NEVER infers topics from private journals
        now = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
        db_session.add(
            JournalEntry(
                user_id=alice["id"],
                local_date=now.date(),
                sleep_minutes=480,
                note="睡眠与休息日记记录",
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        p_sleep = c_bob.post(
            "/api/v1/posts",
            json={"title": "睡眠帖子", "body": "按时睡觉", "category": "睡眠与休息"},
            headers={"X-CSRF-Token": csrf_bob},
        ).json()
        p_sport = c_bob.post(
            "/api/v1/posts",
            json={"title": "运动帖子", "body": "每天快走", "category": "运动与习惯"},
            headers={"X-CSRF-Token": csrf_bob},
        ).json()

        # Anonymous followed_only -> 401
        assert anon.get("/api/v1/posts", params={"followed_only": "true"}).status_code == 401

        # Alice has not followed any category yet -> followed_only returns empty even though she has sleep journal!
        assert c_alice.get("/api/v1/posts", params={"followed_only": "true"}).json()["items"] == []

        # Invalid category -> 422
        assert (
            c_alice.put(
                "/api/v1/me/follows/categories/不存在的话题",
                headers={"X-CSRF-Token": csrf_alice},
            ).status_code
            == 422
        )

        # Idempotent follow "运动与习惯"
        for _ in range(2):
            f_res = c_alice.put(
                "/api/v1/me/follows/categories/运动与习惯",
                headers={"X-CSRF-Token": csrf_alice},
            )
            assert f_res.status_code == 200
            assert f_res.json()["following"] is True

        followed_cats = c_alice.get("/api/v1/me/follows/categories").json()["categories"]
        assert followed_cats == ["运动与习惯"]

        followed_feed = c_alice.get("/api/v1/posts", params={"followed_only": "true"}).json()["items"]
        assert [p["id"] for p in followed_feed] == [p_sport["id"]]
        assert p_sleep["id"] not in [p["id"] for p in followed_feed]

        # Idempotent unfollow
        for _ in range(2):
            uf_res = c_alice.delete(
                "/api/v1/me/follows/categories/运动与习惯",
                headers={"X-CSRF-Token": csrf_alice},
            )
            assert uf_res.status_code == 200
            assert uf_res.json()["following"] is False
        assert c_alice.get("/api/v1/me/follows/categories").json()["categories"] == []
