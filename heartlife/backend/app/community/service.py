from __future__ import annotations

import base64
import json
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy import and_, delete, desc, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.community.schemas import (
    COMMUNITY_CATEGORIES,
    SAFETY_KEYWORDS,
    SAFETY_NOTICE_TEXT,
    CreateCommentRequest,
    CreatePostRequest,
    CreateReportRequest,
    ModerationReasonRequest,
    ResolveReportRequest,
    UpdatePostRequest,
)
from app.core.clock import Clock
from app.core.errors import AppError
from app.db.models import (
    Article,
    Bookmark,
    Comment,
    ModerationAction,
    Post,
    PostTag,
    Reaction,
    Report,
    TopicFollow,
    User,
    UserBlock,
)
from app.notifications.service import create_notification_idempotent


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat()


def compute_safety_notice(title: str, body: str) -> str | None:
    combined = f"{title}\n{body}"
    for kw in SAFETY_KEYWORDS:
        if kw in combined:
            return SAFETY_NOTICE_TEXT
    return None


def encode_post_cursor(created_at: datetime, post_id: str) -> str:
    payload = json.dumps([_ensure_utc(created_at).isoformat(), post_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_post_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        parsed = json.loads(raw)
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not isinstance(parsed[0], str)
            or not isinstance(parsed[1], str)
            or not parsed[1]
        ):
            raise ValueError("Invalid cursor structure")
        dt = _ensure_utc(datetime.fromisoformat(parsed[0]))
        return dt, parsed[1]
    except Exception as exc:
        raise AppError(422, "INVALID_CURSOR", "分页游标不合法") from exc


def _is_blocked_by_viewer(db: Session, viewer: User | None, target_user_id: str) -> bool:
    if viewer is None:
        return False
    row = db.scalar(
        select(UserBlock.id).where(
            UserBlock.blocker_id == viewer.id,
            UserBlock.blocked_id == target_user_id,
        )
    )
    return row is not None


def _get_visible_post_for_viewer(db: Session, post_id: str, viewer: User | None) -> Post:
    post = db.scalar(select(Post).where(Post.id == post_id, Post.status == "visible"))
    if post is None:
        raise AppError(404, "NOT_FOUND", "帖子不存在或不可见")
    if _is_blocked_by_viewer(db, viewer, post.author_id):
        raise AppError(404, "NOT_FOUND", "帖子不存在或不可见")
    return post


def serialize_posts(
    db: Session,
    posts: list[Post],
    viewer: User | None,
    *,
    include_moderation_fields: bool = False,
) -> list[dict]:
    if not posts:
        return []

    post_ids = [p.id for p in posts]
    author_ids = list({p.author_id for p in posts})

    authors = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(author_ids))).all()
    }

    tags_by_post: dict[str, list[str]] = defaultdict(list)
    tag_rows = db.scalars(
        select(PostTag).where(PostTag.post_id.in_(post_ids)).order_by(PostTag.id.asc())
    ).all()
    for tr in tag_rows:
        tags_by_post[tr.post_id].append(tr.tag)

    like_counts: dict[str, int] = dict(
        db.execute(
            select(Reaction.target_id, func.count(Reaction.id))
            .where(Reaction.target_type == "post", Reaction.target_id.in_(post_ids))
            .group_by(Reaction.target_id)
        ).all()
    )

    parent_comment = aliased(Comment)
    comment_counts: dict[str, int] = dict(
        db.execute(
            select(Comment.post_id, func.count(Comment.id))
            .outerjoin(parent_comment, Comment.parent_id == parent_comment.id)
            .where(
                Comment.post_id.in_(post_ids),
                Comment.status == "visible",
                or_(Comment.parent_id.is_(None), parent_comment.status == "visible"),
            )
            .group_by(Comment.post_id)
        ).all()
    )

    viewer_liked_ids: set[str] = set()
    viewer_bookmarked_ids: set[str] = set()
    if viewer is not None:
        viewer_liked_ids = set(
            db.scalars(
                select(Reaction.target_id).where(
                    Reaction.user_id == viewer.id,
                    Reaction.target_type == "post",
                    Reaction.target_id.in_(post_ids),
                )
            ).all()
        )
        viewer_bookmarked_ids = set(
            db.scalars(
                select(Bookmark.target_id).where(
                    Bookmark.user_id == viewer.id,
                    Bookmark.target_type == "post",
                    Bookmark.target_id.in_(post_ids),
                )
            ).all()
        )

    results: list[dict] = []
    for p in posts:
        author = authors.get(p.author_id)
        item: dict[str, object] = {
            "id": p.id,
            "title": p.title,
            "body": p.body,
            "category": p.category,
            "tags": tags_by_post.get(p.id, []),
            "author": {
                "id": p.author_id,
                "nickname": author.nickname if author else "已注销用户",
                "is_demo": author.is_demo if author else False,
            },
            "status": p.status,
            "moderation_reason": p.moderation_reason if (include_moderation_fields or p.status != "visible") else None,
            "like_count": like_counts.get(p.id, 0),
            "comment_count": comment_counts.get(p.id, 0),
            "viewer_liked": p.id in viewer_liked_ids,
            "viewer_bookmarked": p.id in viewer_bookmarked_ids,
            "safety_notice": compute_safety_notice(p.title, p.body),
            "version": p.version,
            "is_demo": p.is_demo,
            "created_at": _iso(p.created_at),
            "updated_at": _iso(p.updated_at),
        }
        results.append(item)
    return results


def create_post(
    db: Session,
    author: User,
    payload: CreatePostRequest,
    clock: Clock,
) -> dict:
    now = clock.now()
    post = Post(
        author_id=author.id,
        category=payload.category,
        title=payload.title,
        body=payload.body,
        status="visible",
        version=1,
        is_demo=False,
        created_at=now,
        updated_at=now,
    )
    db.add(post)
    db.flush()
    for t in payload.tags:
        db.add(PostTag(post_id=post.id, tag=t))
    db.commit()
    db.refresh(post)
    return serialize_posts(db, [post], author)[0]


def list_posts(
    db: Session,
    *,
    viewer: User | None,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    followed_only: bool = False,
    cursor: str | None = None,
    limit: int = 20,
) -> dict:
    stmt = select(Post).where(Post.status == "visible")

    if viewer is not None:
        blocked_subq = select(UserBlock.blocked_id).where(UserBlock.blocker_id == viewer.id)
        stmt = stmt.where(Post.author_id.notin_(blocked_subq))

    if followed_only:
        if viewer is None:
            raise AppError(401, "UNAUTHORIZED", "请先登录后查看关注的话题")
        followed_cats = db.scalars(
            select(TopicFollow.category).where(TopicFollow.user_id == viewer.id)
        ).all()
        if not followed_cats:
            return {"items": [], "next_cursor": None}
        stmt = stmt.where(Post.category.in_(followed_cats))

    if category is not None and category.strip():
        stmt = stmt.where(Post.category == category.strip())

    if tag is not None and tag.strip():
        cleaned_tag = tag.strip()
        stmt = stmt.where(
            exists(
                select(1).where(
                    PostTag.post_id == Post.id,
                    PostTag.tag == cleaned_tag,
                )
            )
        )

    if q is not None and q.strip():
        needle = q.strip().lower()
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        tag_match = exists(
            select(1).where(
                PostTag.post_id == Post.id,
                func.lower(PostTag.tag).like(pattern, escape="\\"),
            )
        )
        stmt = stmt.where(
            or_(
                func.lower(Post.title).like(pattern, escape="\\"),
                func.lower(Post.body).like(pattern, escape="\\"),
                tag_match,
            )
        )

    if cursor is not None and cursor.strip():
        c_dt, c_id = decode_post_cursor(cursor.strip())
        stmt = stmt.where(
            or_(
                Post.created_at < c_dt,
                and_(Post.created_at == c_dt, Post.id < c_id),
            )
        )

    stmt = stmt.order_by(desc(Post.created_at), desc(Post.id)).limit(limit + 1)
    rows = list(db.scalars(stmt).all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_post_cursor(last.created_at, last.id)

    return {
        "items": serialize_posts(db, rows, viewer),
        "next_cursor": next_cursor,
    }


def get_post_detail(db: Session, post_id: str, viewer: User | None) -> dict:
    post = _get_visible_post_for_viewer(db, post_id, viewer)
    return serialize_posts(db, [post], viewer)[0]


def list_my_posts(db: Session, user: User) -> dict:
    rows = list(
        db.scalars(
            select(Post)
            .where(Post.author_id == user.id, Post.status != "deleted")
            .order_by(desc(Post.created_at), desc(Post.id))
        ).all()
    )
    return {"items": serialize_posts(db, rows, user, include_moderation_fields=True)}


def update_post(
    db: Session,
    post_id: str,
    user: User,
    payload: UpdatePostRequest,
    clock: Clock,
) -> dict:
    post = db.scalar(select(Post).where(Post.id == post_id, Post.status != "deleted"))
    if post is None:
        raise AppError(404, "NOT_FOUND", "帖子不存在")
    if post.author_id != user.id:
        raise AppError(403, "FORBIDDEN", "无权编辑他人发布的帖子")

    if payload.title is not None:
        post.title = payload.title
    if payload.body is not None:
        post.body = payload.body
    if payload.category is not None:
        post.category = payload.category
    if payload.tags is not None:
        db.execute(delete(PostTag).where(PostTag.post_id == post.id))
        db.flush()
        for t in payload.tags:
            db.add(PostTag(post_id=post.id, tag=t))

    post.version += 1
    post.updated_at = clock.now()
    db.commit()
    db.refresh(post)
    return serialize_posts(db, [post], user, include_moderation_fields=True)[0]


def delete_post(db: Session, post_id: str, user: User, clock: Clock) -> dict:
    post = db.scalar(select(Post).where(Post.id == post_id, Post.status != "deleted"))
    if post is None:
        raise AppError(404, "NOT_FOUND", "帖子不存在")
    if post.author_id != user.id:
        raise AppError(403, "FORBIDDEN", "无权删除他人发布的帖子")

    post.status = "deleted"
    post.updated_at = clock.now()
    db.commit()
    return {"status": "deleted", "id": post.id}


def like_post(db: Session, post_id: str, user: User, clock: Clock) -> dict:
    _get_visible_post_for_viewer(db, post_id, user)
    existing = db.scalar(
        select(Reaction).where(
            Reaction.user_id == user.id,
            Reaction.target_type == "post",
            Reaction.target_id == post_id,
        )
    )
    if existing is None:
        try:
            with db.begin_nested():
                db.add(
                    Reaction(
                        user_id=user.id,
                        target_type="post",
                        target_id=post_id,
                        created_at=clock.now(),
                    )
                )
                db.flush()
        except IntegrityError:
            pass
        db.commit()

    count = (
        db.scalar(
            select(func.count(Reaction.id)).where(
                Reaction.target_type == "post",
                Reaction.target_id == post_id,
            )
        )
        or 0
    )
    return {"liked": True, "like_count": count}


def unlike_post(db: Session, post_id: str, user: User) -> dict:
    _get_visible_post_for_viewer(db, post_id, user)
    db.execute(
        delete(Reaction).where(
            Reaction.user_id == user.id,
            Reaction.target_type == "post",
            Reaction.target_id == post_id,
        )
    )
    db.commit()
    count = (
        db.scalar(
            select(func.count(Reaction.id)).where(
                Reaction.target_type == "post",
                Reaction.target_id == post_id,
            )
        )
        or 0
    )
    return {"liked": False, "like_count": count}


def _validate_bookmark_target_type(target_type: str) -> str:
    if target_type not in ("post", "article"):
        raise AppError(422, "VALIDATION_ERROR", "收藏目标类型仅支持 post 或 article")
    return target_type


def add_bookmark(
    db: Session,
    target_type: str,
    target_id: str,
    user: User,
    clock: Clock,
) -> dict:
    _validate_bookmark_target_type(target_type)
    if target_type == "post":
        _get_visible_post_for_viewer(db, target_id, user)
    else:
        art = db.scalar(
            select(Article).where(Article.id == target_id, Article.status == "published")
        )
        if art is None:
            raise AppError(404, "NOT_FOUND", "科普文章不存在或未发布")

    existing = db.scalar(
        select(Bookmark).where(
            Bookmark.user_id == user.id,
            Bookmark.target_type == target_type,
            Bookmark.target_id == target_id,
        )
    )
    if existing is None:
        try:
            with db.begin_nested():
                db.add(
                    Bookmark(
                        user_id=user.id,
                        target_type=target_type,
                        target_id=target_id,
                        created_at=clock.now(),
                    )
                )
                db.flush()
        except IntegrityError:
            pass
        db.commit()

    return {"bookmarked": True, "target_type": target_type, "target_id": target_id}


def remove_bookmark(db: Session, target_type: str, target_id: str, user: User) -> dict:
    _validate_bookmark_target_type(target_type)
    db.execute(
        delete(Bookmark).where(
            Bookmark.user_id == user.id,
            Bookmark.target_type == target_type,
            Bookmark.target_id == target_id,
        )
    )
    db.commit()
    return {"bookmarked": False, "target_type": target_type, "target_id": target_id}


def list_my_bookmarks(db: Session, user: User, target_type: str | None = None) -> dict:
    stmt = select(Bookmark).where(Bookmark.user_id == user.id)
    if target_type is not None and target_type != "":
        _validate_bookmark_target_type(target_type)
        stmt = stmt.where(Bookmark.target_type == target_type)
    stmt = stmt.order_by(desc(Bookmark.created_at), desc(Bookmark.id))
    bookmarks = list(db.scalars(stmt).all())

    blocked_ids = set(
        db.scalars(select(UserBlock.blocked_id).where(UserBlock.blocker_id == user.id)).all()
    )

    post_ids = [b.target_id for b in bookmarks if b.target_type == "post"]
    article_ids = [b.target_id for b in bookmarks if b.target_type == "article"]

    visible_posts: dict[str, Post] = {}
    serialized_posts_map: dict[str, dict] = {}
    if post_ids:
        raw_posts = list(
            db.scalars(
                select(Post).where(Post.id.in_(post_ids), Post.status == "visible")
            ).all()
        )
        unblocked_posts = [p for p in raw_posts if p.author_id not in blocked_ids]
        visible_posts = {p.id: p for p in unblocked_posts}
        for sp in serialize_posts(db, unblocked_posts, user):
            serialized_posts_map[sp["id"]] = sp

    published_articles: dict[str, Article] = {}
    if article_ids:
        raw_articles = list(
            db.scalars(
                select(Article).where(
                    Article.id.in_(article_ids),
                    Article.status == "published",
                )
            ).all()
        )
        published_articles = {a.id: a for a in raw_articles}

    items: list[dict] = []
    for b in bookmarks:
        if b.target_type == "post":
            sp = serialized_posts_map.get(b.target_id)
            if sp is None or b.target_id not in visible_posts:
                continue
            items.append(
                {
                    "target_type": "post",
                    "target_id": b.target_id,
                    "title": sp["title"],
                    "category": sp["category"],
                    "created_at": _iso(b.created_at),
                    "post": sp,
                }
            )
        elif b.target_type == "article":
            art = published_articles.get(b.target_id)
            if art is None:
                continue
            items.append(
                {
                    "target_type": "article",
                    "target_id": b.target_id,
                    "title": art.title,
                    "category": art.category,
                    "created_at": _iso(b.created_at),
                    "article": {
                        "id": art.id,
                        "slug": art.slug,
                        "title": art.title,
                        "summary": art.summary,
                        "category": art.category,
                        "published_at": _iso(art.published_at),
                    },
                }
            )
    return {"items": items}


def _serialize_comments(db: Session, comments: list[Comment]) -> list[dict]:
    if not comments:
        return []
    author_ids = list({c.author_id for c in comments})
    authors = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(author_ids))).all()
    }
    out: list[dict] = []
    for c in comments:
        author = authors.get(c.author_id)
        out.append(
            {
                "id": c.id,
                "post_id": c.post_id,
                "parent_id": c.parent_id,
                "body": c.body,
                "author": {
                    "id": c.author_id,
                    "nickname": author.nickname if author else "已注销用户",
                    "is_demo": author.is_demo if author else False,
                },
                "safety_notice": compute_safety_notice("", c.body),
                "created_at": _iso(c.created_at),
                "updated_at": _iso(c.updated_at),
            }
        )
    return out


def list_post_comments(db: Session, post_id: str, viewer: User | None) -> dict:
    _get_visible_post_for_viewer(db, post_id, viewer)
    stmt = select(Comment).where(Comment.post_id == post_id, Comment.status == "visible")
    if viewer is not None:
        blocked_subq = select(UserBlock.blocked_id).where(UserBlock.blocker_id == viewer.id)
        stmt = stmt.where(Comment.author_id.notin_(blocked_subq))

    stmt = stmt.order_by(Comment.created_at.asc(), Comment.id.asc())
    raw_comments = list(db.scalars(stmt).all())

    top_comments = [c for c in raw_comments if c.parent_id is None]
    replies_by_parent: dict[str, list[Comment]] = {}
    for c in raw_comments:
        if c.parent_id is not None:
            replies_by_parent.setdefault(c.parent_id, []).append(c)

    ordered: list[Comment] = []
    for top in top_comments:
        ordered.append(top)
        ordered.extend(replies_by_parent.get(top.id, []))

    return {"items": _serialize_comments(db, ordered)}


def create_comment(
    db: Session,
    post_id: str,
    user: User,
    payload: CreateCommentRequest,
    clock: Clock,
) -> dict:
    post = _get_visible_post_for_viewer(db, post_id, user)

    if payload.request_id is not None:
        existing = db.scalar(
            select(Comment).where(
                Comment.author_id == user.id,
                Comment.request_id == payload.request_id,
            )
        )
        if existing is not None:
            if existing.post_id != post_id:
                raise AppError(409, "CONFLICT", "该 request_id 已用于其他帖子评论")
            return _serialize_comments(db, [existing])[0]

    parent: Comment | None = None
    if payload.parent_id is not None:
        parent = db.scalar(
            select(Comment).where(
                Comment.id == payload.parent_id,
                Comment.post_id == post_id,
            )
        )
        if parent is None or parent.status != "visible":
            raise AppError(404, "NOT_FOUND", "被回复的评论不存在或不可见")
        if _is_blocked_by_viewer(db, user, parent.author_id):
            raise AppError(404, "NOT_FOUND", "被回复的评论不存在或不可见")
        if parent.parent_id is not None:
            raise AppError(422, "MAX_REPLY_DEPTH", "评论最多支持一层回复")

    now = clock.now()
    comment = Comment(
        post_id=post.id,
        author_id=user.id,
        parent_id=payload.parent_id,
        body=payload.body,
        status="visible",
        request_id=payload.request_id,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(comment)
            db.flush()
    except IntegrityError:
        if payload.request_id is not None:
            dup = db.scalar(
                select(Comment).where(
                    Comment.author_id == user.id,
                    Comment.request_id == payload.request_id,
                )
            )
            if dup is not None:
                return _serialize_comments(db, [dup])[0]
        raise

    if parent is None:
        create_notification_idempotent(
            db,
            recipient_id=post.author_id,
            notif_type="post_comment",
            target_type="post",
            target_id=post.id,
            summary=f"{user.nickname} 评论了你的帖子《{post.title[:20]}》",
            dedup_key=f"post_comment:{comment.id}",
            created_at=now,
            actor_id=user.id,
        )
    else:
        create_notification_idempotent(
            db,
            recipient_id=parent.author_id,
            notif_type="comment_reply",
            target_type="post",
            target_id=post.id,
            summary=f"{user.nickname} 回复了你的评论",
            dedup_key=f"comment_reply:{comment.id}",
            created_at=now,
            actor_id=user.id,
        )

    db.commit()
    db.refresh(comment)
    return _serialize_comments(db, [comment])[0]


def delete_comment(db: Session, comment_id: str, user: User, clock: Clock) -> dict:
    comment = db.scalar(
        select(Comment).where(Comment.id == comment_id, Comment.status != "deleted")
    )
    if comment is None:
        raise AppError(404, "NOT_FOUND", "评论不存在")
    if comment.author_id != user.id:
        raise AppError(403, "FORBIDDEN", "无权删除他人评论")

    comment.status = "deleted"
    comment.updated_at = clock.now()
    db.commit()
    return {"status": "deleted", "id": comment.id}


def block_user(db: Session, blocker: User, blocked_id: str, clock: Clock) -> dict:
    if blocked_id == blocker.id:
        raise AppError(422, "CANNOT_BLOCK_SELF", "不能屏蔽自己")
    target = db.scalar(select(User).where(User.id == blocked_id))
    if target is None:
        raise AppError(404, "NOT_FOUND", "目标用户不存在")

    existing = db.scalar(
        select(UserBlock).where(
            UserBlock.blocker_id == blocker.id,
            UserBlock.blocked_id == blocked_id,
        )
    )
    if existing is None:
        try:
            with db.begin_nested():
                db.add(
                    UserBlock(
                        blocker_id=blocker.id,
                        blocked_id=blocked_id,
                        created_at=clock.now(),
                    )
                )
                db.flush()
        except IntegrityError:
            pass
        db.commit()
    return {"blocked": True, "blocked_id": blocked_id}


def unblock_user(db: Session, blocker: User, blocked_id: str) -> dict:
    db.execute(
        delete(UserBlock).where(
            UserBlock.blocker_id == blocker.id,
            UserBlock.blocked_id == blocked_id,
        )
    )
    db.commit()
    return {"blocked": False, "blocked_id": blocked_id}


def list_my_blocks(db: Session, blocker: User) -> dict:
    rows = list(
        db.scalars(
            select(UserBlock)
            .where(UserBlock.blocker_id == blocker.id)
            .order_by(desc(UserBlock.created_at), desc(UserBlock.id))
        ).all()
    )
    blocked_ids = [r.blocked_id for r in rows]
    users_map: dict[str, User] = {}
    if blocked_ids:
        users_map = {
            u.id: u for u in db.scalars(select(User).where(User.id.in_(blocked_ids))).all()
        }
    return {
        "items": [
            {
                "blocked_id": r.blocked_id,
                "nickname": users_map[r.blocked_id].nickname if r.blocked_id in users_map else "未知用户",
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]
    }


def _validate_topic_category(category: str) -> str:
    cleaned = category.strip()
    if cleaned not in COMMUNITY_CATEGORIES:
        raise AppError(422, "INVALID_CATEGORY", "不支持的社区话题分类")
    return cleaned


def follow_category(db: Session, user: User, category: str, clock: Clock) -> dict:
    cat = _validate_topic_category(category)
    existing = db.scalar(
        select(TopicFollow).where(
            TopicFollow.user_id == user.id,
            TopicFollow.category == cat,
        )
    )
    if existing is None:
        try:
            with db.begin_nested():
                db.add(TopicFollow(user_id=user.id, category=cat, created_at=clock.now()))
                db.flush()
        except IntegrityError:
            pass
        db.commit()
    cats = list(
        db.scalars(
            select(TopicFollow.category)
            .where(TopicFollow.user_id == user.id)
            .order_by(TopicFollow.id.asc())
        ).all()
    )
    return {"following": True, "category": cat, "categories": cats}


def unfollow_category(db: Session, user: User, category: str) -> dict:
    cat = _validate_topic_category(category)
    db.execute(
        delete(TopicFollow).where(
            TopicFollow.user_id == user.id,
            TopicFollow.category == cat,
        )
    )
    db.commit()
    cats = list(
        db.scalars(
            select(TopicFollow.category)
            .where(TopicFollow.user_id == user.id)
            .order_by(TopicFollow.id.asc())
        ).all()
    )
    return {"following": False, "category": cat, "categories": cats}


def list_followed_categories(db: Session, user: User) -> dict:
    rows = list(
        db.scalars(
            select(TopicFollow)
            .where(TopicFollow.user_id == user.id)
            .order_by(TopicFollow.id.asc())
        ).all()
    )
    return {
        "categories": [r.category for r in rows],
        "items": [
            {"category": r.category, "created_at": _iso(r.created_at)}
            for r in rows
        ],
    }


def _serialize_report(report: Report, target_preview: dict | None = None) -> dict:
    data: dict[str, object] = {
        "id": report.id,
        "reporter_id": report.reporter_id,
        "target_type": report.target_type,
        "target_id": report.target_id,
        "reason": report.reason,
        "detail": report.detail,
        "status": report.status,
        "resolution_note": report.resolution_note,
        "resolved_by": report.resolved_by,
        "resolved_at": _iso(report.resolved_at),
        "created_at": _iso(report.created_at),
    }
    if target_preview is not None:
        data["target_preview"] = target_preview
    return data


def _serialize_mod_action(action: ModerationAction) -> dict:
    return {
        "id": action.id,
        "actor_id": action.actor_id,
        "report_id": action.report_id,
        "target_type": action.target_type,
        "target_id": action.target_id,
        "action": action.action,
        "reason": action.reason,
        "created_at": _iso(action.created_at),
    }


def create_report(
    db: Session,
    reporter: User,
    payload: CreateReportRequest,
    clock: Clock,
) -> dict:
    if payload.target_type == "post":
        target = db.scalar(
            select(Post).where(Post.id == payload.target_id, Post.status != "deleted")
        )
    else:
        target = db.scalar(
            select(Comment).where(Comment.id == payload.target_id, Comment.status != "deleted")
        )
    if target is None:
        raise AppError(404, "NOT_FOUND", "举报目标不存在或已删除")

    existing_pending = db.scalar(
        select(Report).where(
            Report.reporter_id == reporter.id,
            Report.target_type == payload.target_type,
            Report.target_id == payload.target_id,
            Report.status == "pending",
        )
    )
    if existing_pending is not None:
        return _serialize_report(existing_pending)

    report = Report(
        reporter_id=reporter.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
        detail=payload.detail or "",
        status="pending",
        created_at=clock.now(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _serialize_report(report)


def list_moderation_reports(db: Session, status_filter: str | None = "pending") -> dict:
    stmt = select(Report)
    if status_filter and status_filter != "all":
        if status_filter not in ("pending", "dismissed", "actioned"):
            raise AppError(422, "VALIDATION_ERROR", "不支持的举报状态筛选值")
        stmt = stmt.where(Report.status == status_filter)
    stmt = stmt.order_by(desc(Report.created_at), desc(Report.id))
    reports = list(db.scalars(stmt).all())

    post_ids = [r.target_id for r in reports if r.target_type == "post"]
    comment_ids = [r.target_id for r in reports if r.target_type == "comment"]

    posts_map: dict[str, Post] = {}
    comments_map: dict[str, Comment] = {}
    user_ids: set[str] = set()

    if post_ids:
        for p in db.scalars(select(Post).where(Post.id.in_(post_ids))).all():
            posts_map[p.id] = p
            user_ids.add(p.author_id)
    if comment_ids:
        for c in db.scalars(select(Comment).where(Comment.id.in_(comment_ids))).all():
            comments_map[c.id] = c
            user_ids.add(c.author_id)

    users_map: dict[str, User] = {}
    if user_ids:
        users_map = {
            u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()
        }

    items: list[dict] = []
    for r in reports:
        preview: dict[str, object]
        if r.target_type == "post":
            p = posts_map.get(r.target_id)
            if p is not None:
                author = users_map.get(p.author_id)
                preview = {
                    "type": "post",
                    "id": p.id,
                    "author_id": p.author_id,
                    "author_nickname": author.nickname if author else "未知用户",
                    "category": p.category,
                    "title": p.title,
                    "body": p.body,
                    "status": p.status,
                    "created_at": _iso(p.created_at),
                }
            else:
                preview = {"type": "post", "id": r.target_id, "status": "missing"}
        else:
            c = comments_map.get(r.target_id)
            if c is not None:
                author = users_map.get(c.author_id)
                preview = {
                    "type": "comment",
                    "id": c.id,
                    "post_id": c.post_id,
                    "author_id": c.author_id,
                    "author_nickname": author.nickname if author else "未知用户",
                    "body": c.body,
                    "status": c.status,
                    "created_at": _iso(c.created_at),
                }
            else:
                preview = {"type": "comment", "id": r.target_id, "status": "missing"}

        items.append(_serialize_report(r, target_preview=preview))
    return {"items": items}


def _load_moderation_target(
    db: Session,
    target_type: str,
    target_id: str,
) -> tuple[Post | Comment | None, str | None]:
    if target_type not in ("post", "comment"):
        raise AppError(422, "VALIDATION_ERROR", "审核目标类型仅支持 post 或 comment")
    if target_type == "post":
        p = db.scalar(select(Post).where(Post.id == target_id))
        return p, (p.author_id if p else None)
    c = db.scalar(select(Comment).where(Comment.id == target_id))
    return c, (c.author_id if c else None)


def resolve_moderation_report(
    db: Session,
    report_id: str,
    moderator: User,
    payload: ResolveReportRequest,
    clock: Clock,
) -> dict:
    report = db.scalar(select(Report).where(Report.id == report_id))
    if report is None:
        raise AppError(404, "NOT_FOUND", "举报记录不存在")
    if report.status != "pending":
        raise AppError(409, "REPORT_ALREADY_RESOLVED", "该举报记录已完成审核")

    now = clock.now()
    target, target_author_id = _load_moderation_target(db, report.target_type, report.target_id)

    report.status = payload.decision
    report.resolution_note = payload.reason
    report.resolved_by = moderator.id
    report.resolved_at = now

    should_hide = payload.decision == "actioned" and payload.hide_target
    if should_hide and target is not None and target.status != "deleted":
        target.status = "hidden"
        target.moderation_reason = payload.reason
        target.updated_at = now

    mod_action = ModerationAction(
        actor_id=moderator.id,
        report_id=report.id,
        target_type=report.target_type,
        target_id=report.target_id,
        action="hide" if should_hide else "dismiss",
        reason=payload.reason,
        created_at=now,
    )
    db.add(mod_action)
    db.flush()

    if payload.decision == "actioned" and target_author_id is not None:
        create_notification_idempotent(
            db,
            recipient_id=target_author_id,
            notif_type="moderation_result",
            target_type=report.target_type,
            target_id=report.target_id,
            summary=f"你的社区内容已被审核处理：{payload.reason[:40]}",
            dedup_key=f"mod_action:{mod_action.id}",
            created_at=now,
            actor_id=moderator.id,
        )

    db.commit()
    db.refresh(report)
    return {
        "report": _serialize_report(report),
        "action": _serialize_mod_action(mod_action),
    }


def moderate_hide_content(
    db: Session,
    target_type: str,
    target_id: str,
    moderator: User,
    payload: ModerationReasonRequest,
    clock: Clock,
) -> dict:
    target, target_author_id = _load_moderation_target(db, target_type, target_id)
    if target is None or target.status == "deleted":
        raise AppError(404, "NOT_FOUND", "审核目标不存在或已删除")

    now = clock.now()
    target.status = "hidden"
    target.moderation_reason = payload.reason
    target.updated_at = now

    mod_action = ModerationAction(
        actor_id=moderator.id,
        report_id=None,
        target_type=target_type,
        target_id=target_id,
        action="hide",
        reason=payload.reason,
        created_at=now,
    )
    db.add(mod_action)
    db.flush()

    if target_author_id is not None:
        create_notification_idempotent(
            db,
            recipient_id=target_author_id,
            notif_type="moderation_result",
            target_type=target_type,
            target_id=target_id,
            summary=f"你的社区内容已被审核处理：{payload.reason[:40]}",
            dedup_key=f"mod_action:{mod_action.id}",
            created_at=now,
            actor_id=moderator.id,
        )

    db.commit()
    return {
        "target_type": target_type,
        "target_id": target_id,
        "status": target.status,
        "action": _serialize_mod_action(mod_action),
    }


def moderate_restore_content(
    db: Session,
    target_type: str,
    target_id: str,
    moderator: User,
    payload: ModerationReasonRequest,
    clock: Clock,
) -> dict:
    target, target_author_id = _load_moderation_target(db, target_type, target_id)
    if target is None or target.status == "deleted":
        raise AppError(404, "NOT_FOUND", "审核目标不存在或已删除")

    now = clock.now()
    target.status = "visible"
    target.moderation_reason = None
    target.updated_at = now

    mod_action = ModerationAction(
        actor_id=moderator.id,
        report_id=None,
        target_type=target_type,
        target_id=target_id,
        action="restore",
        reason=payload.reason,
        created_at=now,
    )
    db.add(mod_action)
    db.flush()

    if target_author_id is not None:
        create_notification_idempotent(
            db,
            recipient_id=target_author_id,
            notif_type="moderation_result",
            target_type=target_type,
            target_id=target_id,
            summary=f"你的社区内容已恢复显示：{payload.reason[:40]}",
            dedup_key=f"mod_action:{mod_action.id}",
            created_at=now,
            actor_id=moderator.id,
        )

    db.commit()
    return {
        "target_type": target_type,
        "target_id": target_id,
        "status": target.status,
        "action": _serialize_mod_action(mod_action),
    }


def list_moderation_actions(
    db: Session,
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict:
    stmt = select(ModerationAction)
    if target_type:
        stmt = stmt.where(ModerationAction.target_type == target_type)
    if target_id:
        stmt = stmt.where(ModerationAction.target_id == target_id)
    stmt = stmt.order_by(desc(ModerationAction.created_at), desc(ModerationAction.id))
    rows = list(db.scalars(stmt).all())
    return {"items": [_serialize_mod_action(a) for a in rows]}
