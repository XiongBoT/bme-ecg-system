from __future__ import annotations

"""Populate rich, warm, elderly-friendly synthetic demo content into HeartLife SQLite DB.

Strictly respects:
- DEMO_MODE=1 and local/dev/test environment check
- Zero modifications to backend/app/*, API contracts, or DB schema
- Every synthetic user, post, journal, plan, and challenge is explicitly marked is_demo=True
- Idempotent execution (safe to re-run without duplicating rows)
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.database import build_session_factory  # noqa: E402
from app.db.migrations_runner import run_migrations  # noqa: E402
from app.db.models import (  # noqa: E402
    Article,
    Bookmark,
    Challenge,
    ChallengeMembership,
    Checkin,
    Comment,
    JournalEntry,
    Notification,
    Plan,
    PlanVersion,
    Post,
    PostTag,
    Reaction,
    ReadingDailyLog,
    ReadingHistory,
    TopicFollow,
    User,
)
from app.seed import seed_demo_data  # noqa: E402


def populate_rich_demo(settings: Settings) -> dict[str, int]:
    if not settings.demo_mode:
        raise PermissionError("DEMO_MODE 未启用，拒绝生成丰富演示数据")
    if settings.app_env.lower() not in ("local", "dev", "test"):
        raise PermissionError("仅允许在本地或测试环境生成演示数据")

    run_migrations(settings.database_url)
    seed_demo_data(settings)

    now = datetime.now(timezone.utc)
    shanghai_today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()

    engine, SessionLocal = build_session_factory(settings.database_url)
    try:
        with SessionLocal() as db:
            # 1. Additional warm senior/family demo users (all password: DemoPass123!)
            extra_users_spec = [
                ("demo_wang", "DemoPass123!", "王秀兰（演示）", "退休教师，喜欢清晨公园散步与做清淡家常菜", "member"),
                ("demo_zhang", "DemoPass123!", "张建国（演示）", "每天坚持记录睡眠与午后八段锦练习", "member"),
                ("demo_lin_care", "DemoPass123!", "林小满（演示）", "关注父母日常作息与健康科普学习", "member"),
            ]
            for acc, pwd, nick, bio, roles in extra_users_spec:
                u = db.scalar(select(User).where(User.account == acc))
                if u is None:
                    db.add(
                        User(
                            account=acc,
                            password_hash=hash_password(pwd),
                            nickname=nick,
                            bio=bio,
                            timezone="Asia/Shanghai",
                            roles=roles,
                            status="active",
                            is_demo=True,
                            created_at=now - timedelta(days=10),
                            updated_at=now - timedelta(days=2),
                        )
                    )
            db.flush()

            users = {
                u.account: u
                for u in db.scalars(select(User).where(User.is_demo.is_(True))).all()
            }
            alice = users["demo_alice"]
            bob = users["demo_bob"]
            wang = users["demo_wang"]
            zhang = users["demo_zhang"]
            xiaoman = users["demo_lin_care"]

            # Update demo_alice bio to feel warm and relatable
            alice.bio = "每天早睡一点点，晚饭后沿着小区花园慢走二十五分钟。"

            # 2. Rich Community Posts across all 5 categories
            extra_posts = [
                (
                    wang,
                    "日常健康",
                    "【演示】家里做菜换成控盐小勺两周了，清淡做法其实很鲜美",
                    "以前总觉得菜淡了没味道，后来按科普文章里的方法，出锅前放一点葱花、番茄汁或者香菇提鲜，老伴也说吃着舒服、晚上不容易口渴。慢慢调整口味，一点也不难坚持。",
                    ["减盐饮食", "家常菜", "日常习惯"],
                    2,
                ),
                (
                    zhang,
                    "运动与习惯",
                    "【演示】下雨天不出门时，在客厅阳台练十五分钟舒缓伸展",
                    "以前一遇到阴雨天就坐着看电视一下午。现在定了个温和的小计划：不能去公园慢走的时候，就在客厅窗边做十五分钟肩颈和腿部舒展，活动完浑身暖和。",
                    ["居家活动", "温和运动"],
                    5,
                ),
                (
                    xiaoman,
                    "心脏健康科普交流",
                    "【演示】陪父母去复诊前，提前列好三句话问题单真的很实用",
                    "刚读了百科里《门诊就医前如何高效整理健康问题清单》，上周陪妈妈去门诊前把最近两周的睡眠和散步记录整理在纸上，短短几分钟沟通得特别清楚，医生也夸记录得有条理。",
                    ["门诊沟通", "陪伴家人"],
                    9,
                ),
                (
                    wang,
                    "睡眠与休息",
                    "【演示】午睡控制在半小时以内，晚上入睡踏实多了",
                    "之前午饭后一睡就是一个半小时，结果到了夜里十一点还清醒得很。这周试着定个二十五分钟的轻柔闹钟，下午精神好，晚上十点多自然就有困意了。",
                    ["午休习惯", "规律睡眠"],
                    15,
                ),
                (
                    zhang,
                    "设备使用经验",
                    "【演示】冬天测心电手凉怎么办？先搓热双手静坐几分钟再记录",
                    "天冷刚从外面回来手指冰凉的时候，波形容易抖动。我现在都是先喝口温水、搓搓手静坐五分钟，等呼吸平稳了再开始记录，出来的记录干净清楚。",
                    ["冬季记录", "经验交流"],
                    20,
                ),
                (
                    alice,
                    "日常健康",
                    "【演示】把下午的浓茶换成了温白开和淡菊花水，心慌感少了很多",
                    "连续记了几天健康日记才发现，每次下午喝完浓茶，傍晚就容易觉得心跳快、晚上也睡不沉。改成温开水之后整个人平和不少，记录生活确实能帮自己找到小规律。",
                    ["饮水习惯", "健康日记"],
                    26,
                ),
            ]

            for author, cat, title, body, tags, hours_ago in extra_posts:
                existing_p = db.scalar(select(Post).where(Post.author_id == author.id, Post.title == title))
                if existing_p is None:
                    ts = now - timedelta(hours=hours_ago)
                    p = Post(
                        author_id=author.id,
                        category=cat,
                        title=title,
                        body=body,
                        status="visible",
                        version=1,
                        is_demo=True,
                        created_at=ts,
                        updated_at=ts,
                    )
                    db.add(p)
                    db.flush()
                    for t in tags:
                        db.add(PostTag(post_id=p.id, tag=t))

            db.flush()
            all_posts = list(
                db.scalars(select(Post).where(Post.status == "visible").order_by(Post.created_at.desc())).all()
            )

            # 3. Multi-user likes, bookmarks & warm comments + 1-level replies
            reactors = [alice, bob, wang, zhang, xiaoman]
            for idx, post in enumerate(all_posts):
                for r_user in reactors[(idx % 2) : (idx % 2) + 3]:
                    exists_like = db.scalar(
                        select(Reaction).where(
                            Reaction.user_id == r_user.id,
                            Reaction.target_type == "post",
                            Reaction.target_id == post.id,
                        )
                    )
                    if exists_like is None:
                        db.add(
                            Reaction(
                                user_id=r_user.id,
                                target_type="post",
                                target_id=post.id,
                                created_at=now - timedelta(hours=1),
                            )
                        )

            # Bookmarks for demo_alice (2 posts + 2 articles)
            for p in all_posts[:2]:
                if not db.scalar(
                    select(Bookmark).where(
                        Bookmark.user_id == alice.id,
                        Bookmark.target_type == "post",
                        Bookmark.target_id == p.id,
                    )
                ):
                    db.add(Bookmark(user_id=alice.id, target_type="post", target_id=p.id, created_at=now))

            published_articles = list(
                db.scalars(select(Article).where(Article.status == "published").limit(4)).all()
            )
            for art in published_articles[:2]:
                if not db.scalar(
                    select(Bookmark).where(
                        Bookmark.user_id == alice.id,
                        Bookmark.target_type == "article",
                        Bookmark.target_id == art.id,
                    )
                ):
                    db.add(Bookmark(user_id=alice.id, target_type="article", target_id=art.id, created_at=now))

            # Reading history for demo_alice across 3 days
            for idx, art in enumerate(published_articles[:3]):
                if not db.scalar(
                    select(ReadingHistory).where(
                        ReadingHistory.user_id == alice.id,
                        ReadingHistory.article_id == art.id,
                    )
                ):
                    db.add(
                        ReadingHistory(
                            user_id=alice.id,
                            article_id=art.id,
                            last_read_at=now - timedelta(days=idx),
                        )
                    )
                read_d = shanghai_today - timedelta(days=idx)
                if not db.scalar(
                    select(ReadingDailyLog).where(
                        ReadingDailyLog.user_id == alice.id,
                        ReadingDailyLog.local_date == read_d,
                    )
                ):
                    db.add(ReadingDailyLog(user_id=alice.id, local_date=read_d, created_at=now))

            # Warm comments & 1-level replies on the top posts
            comment_specs = [
                (0, wang, "req-rich-c1", "用香菇和番茄提鲜这个办法真好，今晚家里做汤也试试看！（演示评论）", alice, "req-rich-r1", "确实很鲜，而且不用放味精也很可口，一起坚持！（演示回复）"),
                (1, bob, "req-rich-c2", "阴雨天在窗边舒展十五分钟太实用了，比一直坐着舒服多了。（演示评论）", zhang, "req-rich-r2", "是呀，动作慢一点、配合平稳呼吸就很舒服。（演示回复）"),
                (2, alice, "req-rich-c3", "提前把问题写在小本子上，去医院心里特别踏实，不会出了诊室才想起忘了问。（演示评论）", xiaoman, "req-rich-r3", "没错！长辈看着清清楚楚的清单也很安心。（演示回复）"),
                (3, zhang, "req-rich-c4", "我也是把午休改成了二十五分钟，夜里醒的次数少多了。（演示评论）", None, None, None),
            ]
            for p_idx, c_author, req_id, c_body, r_author, r_req_id, r_body in comment_specs:
                if p_idx >= len(all_posts):
                    continue
                target_post = all_posts[p_idx]
                top_c = db.scalar(select(Comment).where(Comment.request_id == req_id))
                if top_c is None:
                    top_c = Comment(
                        post_id=target_post.id,
                        author_id=c_author.id,
                        parent_id=None,
                        body=c_body,
                        status="visible",
                        request_id=req_id,
                        created_at=now - timedelta(minutes=90 - p_idx * 10),
                        updated_at=now - timedelta(minutes=90 - p_idx * 10),
                    )
                    db.add(top_c)
                    db.flush()
                if r_author and r_req_id and r_body:
                    rep_c = db.scalar(select(Comment).where(Comment.request_id == r_req_id))
                    if rep_c is None:
                        db.add(
                            Comment(
                                post_id=target_post.id,
                                author_id=r_author.id,
                                parent_id=top_c.id,
                                body=r_body,
                                status="visible",
                                request_id=r_req_id,
                                created_at=now - timedelta(minutes=45 - p_idx * 5),
                                updated_at=now - timedelta(minutes=45 - p_idx * 5),
                            )
                        )

            # 4. Topic follows for demo_alice
            for fav_cat in ("睡眠与休息", "日常健康"):
                if not db.scalar(
                    select(TopicFollow).where(
                        TopicFollow.user_id == alice.id,
                        TopicFollow.category == fav_cat,
                    )
                ):
                    db.add(TopicFollow(user_id=alice.id, category=fav_cat, created_at=now))

            # 5. Up-to-date 7-day Journal & Plan Check-ins anchored to real local today (`shanghai_today`)
            recent_journal_specs = [
                (shanghai_today - timedelta(days=5), 435, 25, "good", ["睡得踏实"], "演示记录：十点半熄灯休息"),
                (shanghai_today - timedelta(days=4), 460, 30, "very_good", ["精力充沛"], "演示记录：上午去公园慢走半小时"),
                # Intentionally leave days=3 missing (`null`) so Weekly Report demonstrates honest missing-day handling!
                (shanghai_today - timedelta(days=2), 420, 20, "neutral", ["疲倦"], "演示记录：下午稍微有点困，傍晚散步放松"),
                (shanghai_today - timedelta(days=1), 455, 35, "good", ["无特殊感受", "睡得踏实"], "演示记录：晚饭清淡，睡眠安稳"),
                (shanghai_today, 450, 25, "very_good", ["睡得踏实", "精力充沛"], "演示记录：晨起神清气爽，喝了一杯温水"),
            ]
            for j_date, slp, act, mood, tags, note in recent_journal_specs:
                je = db.scalar(
                    select(JournalEntry).where(
                        JournalEntry.user_id == alice.id,
                        JournalEntry.local_date == j_date,
                    )
                )
                if je is None:
                    db.add(
                        JournalEntry(
                            user_id=alice.id,
                            local_date=j_date,
                            sleep_minutes=slp,
                            activity_minutes=act,
                            mood=mood,
                            symptom_tags_json=json.dumps(tags, ensure_ascii=False),
                            note=note,
                            is_demo=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )

            # Ensure demo_alice has 3 clear daily plans anchored before current week Monday, with 1 checked in today!
            third_plan_title = "阅读一篇健康百科"
            p3 = db.scalar(select(Plan).where(Plan.owner_id == alice.id, Plan.title == third_plan_title))
            if p3 is None:
                start_d = shanghai_today - timedelta(days=10)
                p3 = Plan(
                    owner_id=alice.id,
                    title=third_plan_title,
                    template_key="read_knowledge",
                    active=True,
                    reminder_enabled=True,
                    reminder_time="20:00",
                    is_demo=True,
                    created_at=now - timedelta(days=10),
                    updated_at=now - timedelta(days=10),
                )
                db.add(p3)
                db.flush()
                db.add(
                    PlanVersion(
                        plan_id=p3.id,
                        version_num=1,
                        effective_from=start_d,
                        effective_to=None,
                        weekday_mask=127,
                        active=True,
                        start_date=start_d,
                        end_date=None,
                        reminder_time="20:00",
                        created_at=now - timedelta(days=10),
                    )
                )

            alice_plans = list(db.scalars(select(Plan).where(Plan.owner_id == alice.id)).all())
            for pl in alice_plans:
                # Ensure PlanVersion effective_from covers at least 10 days ago
                vers = list(db.scalars(select(PlanVersion).where(PlanVersion.plan_id == pl.id)).all())
                if vers:
                    earliest = min(vers, key=lambda v: v.version_num)
                    if earliest.effective_from > shanghai_today - timedelta(days=7):
                        earliest.effective_from = shanghai_today - timedelta(days=10)
                        earliest.start_date = shanghai_today - timedelta(days=10)
                for d_back in (4, 3, 2, 1):
                    d_chk = shanghai_today - timedelta(days=d_back)
                    if not db.scalar(
                        select(Checkin).where(Checkin.plan_id == pl.id, Checkin.local_date == d_chk)
                    ):
                        db.add(Checkin(plan_id=pl.id, local_date=d_chk, completed=True, updated_at=now))

            # Mark 1 of Alice's plans completed today so Home shows `1 / 3` realistic in-progress state!
            if alice_plans:
                first_plan = alice_plans[0]
                if not db.scalar(
                    select(Checkin).where(
                        Checkin.plan_id == first_plan.id,
                        Checkin.local_date == shanghai_today,
                    )
                ):
                    db.add(
                        Checkin(
                            plan_id=first_plan.id,
                            local_date=shanghai_today,
                            completed=True,
                            updated_at=now,
                        )
                    )

            # 6. Join 2 Behavioral Challenges for demo_alice
            all_challenges = list(db.scalars(select(Challenge).where(Challenge.active.is_(True))).all())
            for ch in all_challenges[:2]:
                ch.start_date = min(ch.start_date, shanghai_today - timedelta(days=10))
                ch.end_date = max(ch.end_date, shanghai_today + timedelta(days=45))
                if not db.scalar(
                    select(ChallengeMembership).where(
                        ChallengeMembership.challenge_id == ch.id,
                        ChallengeMembership.user_id == alice.id,
                    )
                ):
                    db.add(
                        ChallengeMembership(
                            challenge_id=ch.id,
                            user_id=alice.id,
                            status="active",
                            joined_date=shanghai_today - timedelta(days=6),
                            created_at=now - timedelta(days=6),
                            updated_at=now,
                        )
                    )

            # 7. Helpful In-App Notifications for demo_alice (1 unread, 1 read)
            alice_post = db.scalar(select(Post).where(Post.author_id == alice.id))
            if alice_post is not None:
                n1_key = "demo-rich-notif-1"
                if not db.scalar(
                    select(Notification).where(
                        Notification.recipient_id == alice.id,
                        Notification.dedup_key == n1_key,
                    )
                ):
                    db.add(
                        Notification(
                            recipient_id=alice.id,
                            type="post_comment",
                            target_type="post",
                            target_id=alice_post.id,
                            summary="王秀兰（演示）评论了你的分享：慢慢调整口味一点也不难坚持",
                            dedup_key=n1_key,
                            read_at=None,
                            created_at=now - timedelta(minutes=35),
                        )
                    )
                n2_key = "demo-rich-notif-2"
                if not db.scalar(
                    select(Notification).where(
                        Notification.recipient_id == alice.id,
                        Notification.dedup_key == n2_key,
                    )
                ):
                    db.add(
                        Notification(
                            recipient_id=alice.id,
                            type="comment_reply",
                            target_type="post",
                            target_id=alice_post.id,
                            summary="陈远山（演示）赞同并回复了你的睡前习惯分享",
                            dedup_key=n2_key,
                            read_at=now - timedelta(hours=2),
                            created_at=now - timedelta(hours=3),
                        )
                    )

            db.commit()

            return {
                "users": len(db.scalars(select(User)).all()),
                "posts": len(db.scalars(select(Post).where(Post.status == "visible")).all()),
                "comments": len(db.scalars(select(Comment).where(Comment.status == "visible")).all()),
                "articles": len(db.scalars(select(Article).where(Article.status == "published")).all()),
                "alice_journals": len(
                    db.scalars(select(JournalEntry).where(JournalEntry.user_id == alice.id)).all()
                ),
                "alice_plans": len(db.scalars(select(Plan).where(Plan.owner_id == alice.id)).all()),
            }
    finally:
        engine.dispose()


def main() -> int:
    settings = Settings()
    summary = populate_rich_demo(settings)
    print(f"Rich demo content ready: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
