from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.security import hash_password
from app.db.database import build_session_factory
from app.db.models import (
    Article,
    ArticleRevision,
    Challenge,
    Checkin,
    Comment,
    JournalEntry,
    Plan,
    PlanVersion,
    Post,
    PostTag,
    User,
)

CURATED_ARTICLES = [
    {
        "slug": "single-lead-ecg-scope",
        "title": "单导联心电记录能做什么、不能做什么",
        "category": "设备与指标解读",
        "summary": "了解便携式单导联心电记录的节律筛查定位，以及为何不能替代医院十二导联心电图。",
        "body": "便携式单导联心电设备通常用于记录特定时段的心率与节律变化趋势，便于居家留存片段供就医参考。\n\n需要注意，单导联视角有限，无法全面观察心脏各个方位的电活动，因此不能用于排查心肌缺血、急性心肌梗死或结构性心脏问题。若出现胸闷、胸痛、晕厥或持续不适，请及时前往医疗机构完成标准十二导联检查。",
        "sources": [
            {"title": "American Heart Association - Electrocardiogram (ECG or EKG)", "url": "https://www.heart.org/en/health-topics/heart-attack/diagnosing-a-heart-attack/electrocardiogram-ecg-or-ekg", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "heart-rate-vs-rhythm",
        "title": "心率与心律：两个常被混淆的基础概念",
        "category": "心脏基础知识",
        "summary": "心率关注每分钟跳动快慢，心律关注跳动间隔是否整齐规律。",
        "body": "在日常记录中，心率（Heart Rate）指每分钟心跳的次数；而心律（Heart Rhythm）指心跳搏动的节律与起源是否规整。\n\n安静状态下成年人心率常见范围为 60–100 次/分，但运动、睡眠、情绪波动、咖啡因摄入都会引起生理性波动。偶发的节律波动未必代表疾病，建议结合休息状态与医生评估综合看待。",
        "sources": [
            {"title": "AHA - All About Heart Rate (Pulse)", "url": "https://www.heart.org/en/health-topics/high-blood-pressure/the-facts-about-high-blood-pressure/all-about-heart-rate-pulse", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "sleep-regularity-heart",
        "title": "规律睡眠为什么是心血管健康的重要基石",
        "category": "睡眠与休息",
        "summary": "入睡和起床时间的稳定性与睡眠总时长同样值得关注。",
        "body": "世界卫生组织与心血管健康指南将充足且规律的睡眠列为日常健康管理的核心要素之一。\n\n成年人一般建议保持每晚 7–9 小时的规律睡眠。睡前减少强光屏幕刺激、避免晚间过量摄入浓茶或咖啡、固定起床时间，有助于维持自主神经平衡。",
        "sources": [
            {"title": "NHLBI - How Sleep Works & Heart Health", "url": "https://www.nhlbi.nih.gov/health/sleep-deprivation/health-effects", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "daily-moderate-activity",
        "title": "温和、可持续的日常活动习惯建立指南",
        "category": "运动与习惯",
        "summary": "不必追求高强度极限运动，规律步行与减少久坐同样有益。",
        "body": "世界卫生组织身体活动指南建议成年人每周循序渐进开展适度有氧活动，同时打断长时间久坐。\n\n对于刚开始建立习惯的人群，可以从每天 15–20 分钟平地散步、伸展活动开始，以交谈自然、不感到明显气促为宜。若存在既有心血管病史，调整运动强度前应先咨询主管医生。",
        "sources": [
            {"title": "WHO Guidelines on Physical Activity and Sedentary Behaviour", "url": "https://www.who.int/news-room/fact-sheets/detail/physical-activity", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "how-to-keep-health-journal",
        "title": "如何记录一份清晰实用的日常健康日记",
        "category": "日常记录方法",
        "summary": "记录睡眠、活动、心情与主观感受，为自我觉察和门诊沟通提供客观时间线。",
        "body": "高质量的健康日记不在于堆砌复杂指标，而在于真实记录发生时间、持续时长与伴随场景。\n\n例如记录心悸或疲倦感时，可简要记下当时是在静息、熬夜后还是快走时出现，持续了几分钟，休息后是否缓解。没有记录的日期留空即可，无需补零。",
        "sources": [
            {"title": "CDC - Living With a Heart Condition: Tracking Daily Habits", "url": "https://www.cdc.gov/heart-disease/about/index.html", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "prepare-for-clinic-visit",
        "title": "门诊就医前如何高效整理健康问题清单",
        "category": "就医与沟通",
        "summary": "提前整理近期症状时间线、正在使用的药物清单与核心疑问。",
        "body": "门诊沟通时间宝贵，建议就诊前准备三项简明信息：\n1. 近期不适出现的具体日期、诱因与缓解方式；\n2. 目前正在规律服用的全部药物或保健品名称；\n3. 本次最想请医生解答的 2–3 个问题。\n\n携带纸质或导出的摘要记录可以帮助医生快速了解日常背景，但最终检查方案应以临床判断为准。",
        "sources": [
            {"title": "NIH National Institute on Aging - Talking With Your Doctor", "url": "https://www.nia.nih.gov/health/health-care-professionals-information/talking-your-older-patients", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "caffeine-hydration-rhythm",
        "title": "饮水、咖啡因与日常心悸感受的关系",
        "category": "日常健康",
        "summary": "脱水、浓茶与咖啡因敏感度可能影响部分人群的主观心跳感受。",
        "body": "部分对咖啡因敏感的人群在饮用浓咖啡、浓茶或能量饮料后，可能更容易察觉到心跳加快或心悸感；夏季出汗多、饮水不足时也可能出现类似体感。\n\n可通过健康日记观察饮品摄入时间与睡眠、心悸自述之间的个人规律，温和调整作息。",
        "sources": [
            {"title": "MedlinePlus - Heart Palpitations Overview", "url": "https://medlineplus.gov/heartpalpitations.html", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "stress-breathing-relaxation",
        "title": "情绪压力管理与温和呼吸放松练习",
        "category": "睡眠与休息",
        "summary": "紧张焦虑常伴随交感神经兴奋，简短的缓慢呼吸练习有助于平复身心。",
        "body": "长期紧绷与焦虑会影响睡眠质量，并放大对躯体感觉的关注。\n\n在安静安全的座位上，尝试每分钟约 6 次的平缓腹式呼吸（如吸气 4 秒、呼气 6 秒，持续 3–5 分钟），不强迫屏气。若练习中感到头晕，恢复自然呼吸即可。",
        "sources": [
            {"title": "AHA - Stress and Heart Health", "url": "https://www.heart.org/en/healthy-living/healthy-lifestyle/stress-management/stress-and-heart-health", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "balanced-sodium-diet",
        "title": "日常饮食减盐与清淡均衡小贴士",
        "category": "日常健康",
        "summary": "关注隐形盐来源，逐步用天然香料与新鲜食材替代重口味调味。",
        "body": "世界卫生组织建议成年人每日食盐摄入量控制在 5 克以下。除了烹饪用盐，酱油、腌制品、加工肉类与咸味零食也是常见的隐形钠来源。\n\n逐步减少外食汤底摄入，多用葱姜蒜、柠檬汁或番茄提味，让味蕾在 2–3 周内自然适应清爽口味。",
        "sources": [
            {"title": "WHO - Salt Reduction Fact Sheet", "url": "https://www.who.int/news-room/fact-sheets/detail/salt-reduction", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "privacy-in-health-communities",
        "title": "参与线上健康社区时如何保护个人隐私",
        "category": "隐私与安全",
        "summary": "使用昵称交流生活经验，不公开真实姓名、身份证号、住址或未脱敏病历单。",
        "body": "同伴互助社区有助于分享作息养成心得与情绪支持，但公开网络空间需注意个人隐私边界：\n1. 请勿在帖子或评论中发布手机号、微信号、家庭住址或医院就诊卡号；\n2. 请勿替代医生为他人开具药名、剂量或停药建议；\n3. 私密日记保存在个人空间即可，仅将愿意公开的一般生活经验发往社区。",
        "sources": [
            {"title": "WHO - Digital Health Literacy & Patient Safety Principles", "url": "https://www.who.int/health-topics/digital-health", "accessed_at": "2026-11-26"}
        ],
    },
    {
        "slug": "warning-signs-emergency",
        "title": "哪些突发症状不应等待观察，需立即就医",
        "category": "就医与沟通",
        "summary": "识别压榨性胸痛、呼吸困难、晕厥等危险信号，第一时间联系急救。",
        "body": "健康管理软件无法处理急性医疗风险。当本人或身边人突发以下情况时，请勿在线发帖等待回复，应立即拨打当地急救电话（如 120）：\n- 持续不缓解的胸痛、胸口压迫感或放射至左肩背/下颌疼痛；\n- 明显呼吸困难、大汗淋漓、面色苍白；\n- 突发晕厥、意识模糊或单侧肢体无力、言语不清。",
        "sources": [
            {"title": "AHA - Warning Signs of a Heart Attack", "url": "https://www.heart.org/en/health-topics/heart-attack/warning-signs-of-a-heart-attack", "accessed_at": "2026-11-26"}
        ],
    },
]


def sync_article_fts(db, article: Article) -> None:
    db.execute(text("DELETE FROM articles_fts WHERE article_id = :aid"), {"aid": article.id})
    if article.status == "published":
        db.execute(
            text(
                """
                INSERT INTO articles_fts (article_id, title, summary, category, body)
                VALUES (:aid, :title, :summary, :category, :body)
                """
            ),
            {
                "aid": article.id,
                "title": article.title,
                "summary": article.summary,
                "category": article.category,
                "body": article.body,
            },
        )


def seed_demo_data(settings: Settings) -> dict[str, int]:
    if not settings.demo_mode:
        raise PermissionError("DEMO_MODE 未启用，拒绝写入演示数据")
    if settings.app_env.lower() not in ("local", "dev", "test"):
        raise PermissionError("仅允许在本地或测试环境执行演示数据初始化")

    _, SessionLocal = build_session_factory(settings.database_url)
    now = datetime(2026, 11, 26, 9, 0, 0, tzinfo=timezone.utc)
    today = date(2026, 11, 26)

    with SessionLocal() as db:
        demo_users_spec = [
            ("demo_alice", "DemoPass123!", "林晓禾（演示）", "规律作息与散步打卡中", "member"),
            ("demo_bob", "DemoPass123!", "陈远山（演示）", "关注睡眠与慢跑恢复", "member"),
            ("demo_mod", "DemoPass123!", "社区审核员（演示）", "维护友善安全的交流环境", "member,moderator"),
            ("demo_editor", "DemoPass123!", "科普编辑（演示）", "整理公开健康科普资料", "member,editor,moderator"),
        ]
        user_map: dict[str, User] = {}
        for account, pwd, nick, bio, roles in demo_users_spec:
            u = db.scalar(select(User).where(User.account == account))
            if u is None:
                u = User(
                    account=account,
                    password_hash=hash_password(pwd),
                    nickname=nick,
                    bio=bio,
                    timezone="Asia/Shanghai",
                    roles=roles,
                    status="active",
                    is_demo=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(u)
                db.flush()
            user_map[account] = u

        editor = user_map["demo_editor"]
        alice = user_map["demo_alice"]
        bob = user_map["demo_bob"]

        # Curated Encyclopedia Articles (idempotent by slug)
        review_meta = {
            "reviewer": "课程内容组（演示核验）",
            "review_type": "课程内容审核",
            "reviewed_at": "2026-11-26",
            "note": "演示种子科普条目，已附公开权威机构参考链接，非临床诊疗指南。",
        }
        for idx, spec in enumerate(CURATED_ARTICLES):
            art = db.scalar(select(Article).where(Article.slug == spec["slug"]))
            if art is None:
                art = Article(
                    slug=spec["slug"],
                    editor_id=editor.id,
                    status="published",
                    title=spec["title"],
                    summary=spec["summary"],
                    category=spec["category"],
                    body=spec["body"],
                    author_byline="HeartLife 课程科普组",
                    scope_note="仅用于日常健康生活科普参考，不作为个体化临床诊断或用药建议。",
                    sources_json=json.dumps(spec["sources"], ensure_ascii=False),
                    review_record_json=json.dumps(review_meta, ensure_ascii=False),
                    revision=1,
                    is_demo=True,
                    published_at=now - timedelta(hours=idx),
                    created_at=now - timedelta(hours=idx),
                    updated_at=now - timedelta(hours=idx),
                )
                db.add(art)
                db.flush()
                db.add(
                    ArticleRevision(
                        article_id=art.id,
                        editor_id=editor.id,
                        revision=1,
                        title=art.title,
                        body=art.body,
                        sources_json=art.sources_json,
                        review_record_json=art.review_record_json,
                        created_at=now - timedelta(hours=idx),
                    )
                )
            sync_article_fts(db, art)

        # Synthetic Demo Posts (idempotent by title + author)
        demo_posts = [
            (
                alice,
                "睡眠与休息",
                "【演示】把手机放到卧室门外两周，入睡确实快了不少",
                "以前睡前总会刷半小时消息，越看越精神。最近试着22:30把手机放在客厅充电，改看十页纸质书，连续记录了一周睡眠时长，醒来轻松很多。",
                ["规律作息", "睡前习惯"],
            ),
            (
                bob,
                "运动与习惯",
                "【演示】晚饭后二十分钟河边散步，比定高目标更容易坚持",
                "之前总想一次跑五公里结果三天就放弃了。现在改成每天晚饭后散步20分钟，不追求配速，反而连续打卡下来了。",
                ["散步", "微习惯"],
            ),
            (
                alice,
                "心脏健康科普交流",
                "【演示】读完心率与心律那篇科普，不再因为运动后心跳快自己吓自己了",
                "学会区分静息状态和活动后的生理波动挺有用的，平时记下当时的状态和睡眠，去门诊沟通也更有条理。",
                ["科普笔记", "日常记录"],
            ),
            (
                bob,
                "设备使用经验",
                "【演示】居家测心电前安静坐五分钟，减少手部晃动干扰",
                "分享一个日常使用小经验：刚爬完楼梯马上测容易有很多肌电干扰，先静坐平复几分钟、手放平，记录质量稳定很多。",
                ["使用心得", "居家记录"],
            ),
        ]
        first_post_id: str | None = None
        for idx, (author, cat, title, body, tags) in enumerate(demo_posts):
            p = db.scalar(select(Post).where(Post.author_id == author.id, Post.title == title))
            if p is None:
                p = Post(
                    author_id=author.id,
                    category=cat,
                    title=title,
                    body=body,
                    status="visible",
                    version=1,
                    is_demo=True,
                    created_at=now - timedelta(hours=12 - idx),
                    updated_at=now - timedelta(hours=12 - idx),
                )
                db.add(p)
                db.flush()
                for t in tags:
                    db.add(PostTag(post_id=p.id, tag=t))
            if first_post_id is None:
                first_post_id = p.id

        if first_post_id is not None:
            existing_comment = db.scalar(
                select(Comment).where(Comment.post_id == first_post_id, Comment.author_id == bob.id)
            )
            if existing_comment is None:
                db.add(
                    Comment(
                        post_id=first_post_id,
                        author_id=bob.id,
                        body="同感！把闹钟换成传统小闹钟也很有帮助（演示评论）。",
                        status="visible",
                        request_id="seed-comment-1",
                        created_at=now - timedelta(hours=6),
                        updated_at=now - timedelta(hours=6),
                    )
                )

        # Synthetic Demo Plans & Journals for demo_alice
        demo_plans = [
            ("每日记录睡眠", "sleep_log", 127, "21:30"),
            ("晚饭后散步 20 分钟", "walk_habit", 127, "19:30"),
        ]
        for title, tpl_key, mask, rtime in demo_plans:
            pl = db.scalar(select(Plan).where(Plan.owner_id == alice.id, Plan.title == title))
            if pl is None:
                start_d = today - timedelta(days=6)
                pl = Plan(
                    owner_id=alice.id,
                    title=title,
                    template_key=tpl_key,
                    active=True,
                    reminder_enabled=True,
                    reminder_time=rtime,
                    is_demo=True,
                    created_at=now - timedelta(days=6),
                    updated_at=now - timedelta(days=6),
                )
                db.add(pl)
                db.flush()
                db.add(
                    PlanVersion(
                        plan_id=pl.id,
                        version_num=1,
                        effective_from=start_d,
                        effective_to=None,
                        weekday_mask=mask,
                        active=True,
                        start_date=start_d,
                        end_date=None,
                        reminder_time=rtime,
                        created_at=now - timedelta(days=6),
                    )
                )
                for offset in (3, 2, 1):
                    d_chk = today - timedelta(days=offset)
                    db.add(Checkin(plan_id=pl.id, local_date=d_chk, completed=True, updated_at=now))

        demo_journals = [
            (today - timedelta(days=3), 450, 25, "good", ["无特殊感受"], "演示记录：睡眠平稳"),
            (today - timedelta(days=2), 430, 30, "very_good", ["精力充沛"], "演示记录：傍晚河边散步"),
            (today - timedelta(days=1), 465, 20, "good", ["无特殊感受"], "演示记录：按时休息"),
        ]
        for j_date, slp, act, mood, tags, note in demo_journals:
            je = db.scalar(
                select(JournalEntry).where(JournalEntry.user_id == alice.id, JournalEntry.local_date == j_date)
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

        # Synthetic P1 Behavioral Challenges
        challenges_spec = [
            (
                "sleep-7d",
                "7 日规律睡眠记录",
                "连续或累计 7 天在健康日记中记录本人睡眠时长，培养作息觉察。",
                "journal_sleep",
                7,
                "规律作息记录者",
            ),
            (
                "knowledge-7d",
                "7 日心脏健康科普共读",
                "累计 7 天阅读已审核健康百科文章，温和积累科学常识。",
                "read_article",
                7,
                "理性健康学习者",
            ),
            (
                "habit-7d",
                "7 日自定微习惯打卡",
                "按个人节奏累计 7 天完成任意一项自定健康计划打卡。",
                "plan_checkin",
                7,
                "微习惯践行者",
            ),
        ]
        for slug, title, desc, rtype, tdays, badge in challenges_spec:
            ch = db.scalar(select(Challenge).where(Challenge.slug == slug))
            if ch is None:
                db.add(
                    Challenge(
                        slug=slug,
                        title=title,
                        description=desc,
                        rule_type=rtype,
                        target_days=tdays,
                        start_date=today - timedelta(days=14),
                        end_date=today + timedelta(days=60),
                        badge_title=badge,
                        active=True,
                        is_demo=True,
                        created_at=now,
                    )
                )

        db.commit()

        return {
            "users": len(db.scalars(select(User)).all()),
            "articles": len(db.scalars(select(Article)).all()),
            "posts": len(db.scalars(select(Post)).all()),
            "challenges": len(db.scalars(select(Challenge)).all()),
        }
