from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from sqlalchemy import and_, delete, desc, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock, user_local_date
from app.core.errors import AppError
from app.db.models import (
    Article,
    ArticleRevision,
    Bookmark,
    ReadingDailyLog,
    ReadingHistory,
    User,
)
from app.knowledge.schemas import (
    STANDARD_ARTICLE_CATEGORIES,
    CreateArticleRequest,
    PublishArticleRequest,
    ReviewRecord,
    SourceItem,
    UpdateArticleRequest,
)
from app.seed import sync_article_fts

_FTS_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _encode_article_cursor(published_at: datetime, article_id: str) -> str:
    ts = _iso_utc(published_at) or ""
    raw = json.dumps({"ts": ts, "id": article_id}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_article_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        dt = datetime.fromisoformat(payload["ts"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        art_id = str(payload["id"])
        if not art_id:
            raise ValueError("empty id")
        return dt, art_id
    except Exception as exc:
        raise AppError(422, "INVALID_CURSOR", "分页游标不合法") from exc


def _parse_sources(sources_json: str | None) -> list[dict]:
    if not sources_json:
        return []
    try:
        parsed = json.loads(sources_json)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _parse_review_record(review_json: str | None) -> dict | None:
    if not review_json:
        return None
    try:
        parsed = json.loads(review_json)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _bookmarked_article_ids(db: Session, user_id: str | None, article_ids: list[str]) -> set[str]:
    if not user_id or not article_ids:
        return set()
    rows = db.scalars(
        select(Bookmark.target_id).where(
            Bookmark.user_id == user_id,
            Bookmark.target_type == "article",
            Bookmark.target_id.in_(article_ids),
        )
    ).all()
    return set(rows)


def serialize_article_summary(article: Article, *, viewer_bookmarked: bool = False) -> dict:
    return {
        "id": article.id,
        "slug": article.slug,
        "title": article.title,
        "summary": article.summary,
        "category": article.category,
        "author_byline": article.author_byline,
        "scope_note": article.scope_note,
        "revision": article.revision,
        "is_demo": article.is_demo,
        "status": article.status,
        "published_at": _iso_utc(article.published_at),
        "updated_at": _iso_utc(article.updated_at),
        "viewer_bookmarked": viewer_bookmarked,
    }


def serialize_article_detail(article: Article, *, viewer_bookmarked: bool = False) -> dict:
    return {
        **serialize_article_summary(article, viewer_bookmarked=viewer_bookmarked),
        "body": article.body,
        "sources": _parse_sources(article.sources_json),
        "review_record": _parse_review_record(article.review_record_json),
    }


def serialize_revision(rev: ArticleRevision) -> dict:
    return {
        "id": rev.id,
        "article_id": rev.article_id,
        "editor_id": rev.editor_id,
        "revision": rev.revision,
        "title": rev.title,
        "body": rev.body,
        "sources": _parse_sources(rev.sources_json),
        "review_record": _parse_review_record(rev.review_record_json),
        "created_at": _iso_utc(rev.created_at),
    }


def list_article_categories(db: Session) -> list[str]:
    db_cats = db.scalars(
        select(Article.category).where(Article.status == "published").distinct()
    ).all()
    merged = list(STANDARD_ARTICLE_CATEGORIES)
    for c in db_cats:
        if c and c not in merged:
            merged.append(c)
    return merged


def _matching_published_ids_for_query(db: Session, q: str) -> set[str]:
    cleaned = q.strip()
    if not cleaned:
        return set()

    matched_ids: set[str] = set()
    tokens = _FTS_TOKEN_RE.findall(cleaned)
    if tokens:
        fts_expr = " OR ".join(f'"{t}"' for t in tokens[:8])
        try:
            fts_rows = db.execute(
                text(
                    """
                    SELECT f.article_id
                    FROM articles_fts f
                    JOIN articles a ON a.id = f.article_id
                    WHERE a.status = 'published' AND articles_fts MATCH :expr
                    """
                ),
                {"expr": fts_expr},
            ).scalars().all()
            matched_ids.update(fts_rows)
        except Exception:
            pass

    terms = [part for part in cleaned.split() if part]
    like_clauses = []
    for term in terms[:6]:
        pat = f"%{term}%"
        like_clauses.append(
            or_(
                Article.title.like(pat),
                Article.summary.like(pat),
                Article.category.like(pat),
                Article.body.like(pat),
            )
        )
    if like_clauses:
        like_rows = db.scalars(
            select(Article.id).where(Article.status == "published", *like_clauses)
        ).all()
        matched_ids.update(like_rows)

    return matched_ids


def list_published_articles(
    db: Session,
    *,
    category: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    viewer: User | None = None,
) -> dict:
    stmt = select(Article).where(Article.status == "published")

    if category and category.strip():
        stmt = stmt.where(Article.category == category.strip())

    if q and q.strip():
        matched_ids = _matching_published_ids_for_query(db, q)
        if not matched_ids:
            return {"items": [], "next_cursor": None}
        stmt = stmt.where(Article.id.in_(matched_ids))

    if cursor:
        cursor_dt, cursor_id = _decode_article_cursor(cursor)
        stmt = stmt.where(
            or_(
                Article.published_at < cursor_dt,
                and_(Article.published_at == cursor_dt, Article.id < cursor_id),
            )
        )

    stmt = stmt.order_by(desc(Article.published_at), desc(Article.id)).limit(limit + 1)
    rows = list(db.scalars(stmt).all())

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page and page[-1].published_at is not None:
        next_cursor = _encode_article_cursor(page[-1].published_at, page[-1].id)

    bookmarked_ids = _bookmarked_article_ids(
        db, viewer.id if viewer else None, [a.id for a in page]
    )
    return {
        "items": [
            serialize_article_summary(a, viewer_bookmarked=(a.id in bookmarked_ids))
            for a in page
        ],
        "next_cursor": next_cursor,
    }


def get_published_article_detail(
    db: Session, article_id: str, *, viewer: User | None = None
) -> dict:
    art = db.scalar(
        select(Article).where(Article.id == article_id, Article.status == "published")
    )
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在或尚未发布")
    bookmarked = bool(
        viewer
        and db.scalar(
            select(Bookmark.id).where(
                Bookmark.user_id == viewer.id,
                Bookmark.target_type == "article",
                Bookmark.target_id == art.id,
            )
        )
    )
    return serialize_article_detail(art, viewer_bookmarked=bookmarked)


def upsert_reading_history(
    db: Session, user: User, article_id: str, clock: Clock
) -> dict:
    art = db.scalar(
        select(Article).where(Article.id == article_id, Article.status == "published")
    )
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在或尚未发布")

    now = clock.now()
    entry = db.scalar(
        select(ReadingHistory).where(
            ReadingHistory.user_id == user.id,
            ReadingHistory.article_id == article_id,
        )
    )
    if entry is None:
        entry = ReadingHistory(user_id=user.id, article_id=article_id, last_read_at=now)
        db.add(entry)
    else:
        entry.last_read_at = now

    local_d = user_local_date(clock, user.timezone)
    daily = db.scalar(
        select(ReadingDailyLog).where(
            ReadingDailyLog.user_id == user.id,
            ReadingDailyLog.local_date == local_d,
        )
    )
    if daily is None:
        db.add(ReadingDailyLog(user_id=user.id, local_date=local_d, created_at=now))

    db.commit()
    return {
        "article_id": art.id,
        "last_read_at": _iso_utc(now),
        "local_date": local_d.isoformat(),
    }


def list_reading_history(db: Session, user: User) -> dict:
    rows = db.execute(
        select(ReadingHistory, Article)
        .join(Article, Article.id == ReadingHistory.article_id)
        .where(
            ReadingHistory.user_id == user.id,
            Article.status == "published",
        )
        .order_by(desc(ReadingHistory.last_read_at), desc(ReadingHistory.id))
    ).all()

    art_ids = [art.id for _, art in rows]
    bm_ids = _bookmarked_article_ids(db, user.id, art_ids)
    items = []
    for rh, art in rows:
        summary = serialize_article_summary(art, viewer_bookmarked=(art.id in bm_ids))
        items.append(
            {
                "article_id": art.id,
                "id": art.id,
                "title": art.title,
                "summary": art.summary,
                "category": art.category,
                "last_read_at": _iso_utc(rh.last_read_at),
                "article": summary,
            }
        )
    return {"items": items}


def clear_reading_history(db: Session, user: User) -> dict:
    res = db.execute(delete(ReadingHistory).where(ReadingHistory.user_id == user.id))
    db.commit()
    return {"deleted": res.rowcount or 0}


def set_article_bookmark(
    db: Session, user: User, article_id: str, clock: Clock
) -> dict:
    art = db.scalar(
        select(Article).where(Article.id == article_id, Article.status == "published")
    )
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在或尚未发布")

    existing = db.scalar(
        select(Bookmark).where(
            Bookmark.user_id == user.id,
            Bookmark.target_type == "article",
            Bookmark.target_id == article_id,
        )
    )
    if existing is None:
        db.add(
            Bookmark(
                user_id=user.id,
                target_type="article",
                target_id=article_id,
                created_at=clock.now(),
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"article_id": article_id, "bookmarked": True}


def remove_article_bookmark(db: Session, user: User, article_id: str) -> dict:
    db.execute(
        delete(Bookmark).where(
            Bookmark.user_id == user.id,
            Bookmark.target_type == "article",
            Bookmark.target_id == article_id,
        )
    )
    db.commit()
    return {"article_id": article_id, "bookmarked": False}


def list_article_bookmarks(db: Session, user: User) -> dict:
    rows = db.execute(
        select(Bookmark, Article)
        .join(Article, Article.id == Bookmark.target_id)
        .where(
            Bookmark.user_id == user.id,
            Bookmark.target_type == "article",
            Article.status == "published",
        )
        .order_by(desc(Bookmark.created_at), desc(Bookmark.id))
    ).all()
    items = []
    for bm, art in rows:
        items.append(
            {
                **serialize_article_summary(art, viewer_bookmarked=True),
                "article_id": art.id,
                "bookmarked_at": _iso_utc(bm.created_at),
            }
        )
    return {"items": items}


# ---------------- Editorial Management ----------------


def editor_list_articles(db: Session, *, status_filter: str | None = None) -> dict:
    stmt = select(Article)
    if status_filter and status_filter.strip():
        stmt = stmt.where(Article.status == status_filter.strip())
    stmt = stmt.order_by(desc(Article.updated_at), desc(Article.id))
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                **serialize_article_detail(a, viewer_bookmarked=False),
                "editor_id": a.editor_id,
                "created_at": _iso_utc(a.created_at),
            }
            for a in rows
        ]
    }


def editor_get_article(db: Session, article_id: str) -> dict:
    art = db.scalar(select(Article).where(Article.id == article_id))
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在")
    revs = db.scalars(
        select(ArticleRevision)
        .where(ArticleRevision.article_id == art.id)
        .order_by(ArticleRevision.revision.asc())
    ).all()
    return {
        **serialize_article_detail(art, viewer_bookmarked=False),
        "editor_id": art.editor_id,
        "created_at": _iso_utc(art.created_at),
        "revisions": [serialize_revision(r) for r in revs],
    }


def editor_create_article(
    db: Session, editor: User, payload: CreateArticleRequest, clock: Clock
) -> dict:
    if payload.slug:
        dup = db.scalar(select(Article.id).where(Article.slug == payload.slug))
        if dup is not None:
            raise AppError(409, "SLUG_EXISTS", "文章标识 slug 已存在")

    now = clock.now()
    sources_str = json.dumps(
        [s.model_dump(exclude_none=True) for s in payload.sources], ensure_ascii=False
    )
    review_str = (
        json.dumps(payload.review_record.model_dump(exclude_none=True), ensure_ascii=False)
        if payload.review_record is not None
        else None
    )

    art = Article(
        slug=payload.slug,
        editor_id=editor.id,
        status="draft",
        title=payload.title,
        summary=payload.summary,
        category=payload.category,
        body=payload.body,
        author_byline=payload.author_byline,
        scope_note=payload.scope_note,
        sources_json=sources_str,
        review_record_json=review_str,
        revision=1,
        is_demo=False,
        published_at=None,
        created_at=now,
        updated_at=now,
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
            created_at=now,
        )
    )
    db.commit()
    db.refresh(art)
    return {
        **serialize_article_detail(art, viewer_bookmarked=False),
        "editor_id": art.editor_id,
        "created_at": _iso_utc(art.created_at),
    }


def editor_update_article(
    db: Session,
    editor: User,
    article_id: str,
    payload: UpdateArticleRequest,
    clock: Clock,
) -> dict:
    art = db.scalar(select(Article).where(Article.id == article_id))
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在")

    if payload.title is not None:
        art.title = payload.title
    if payload.summary is not None:
        art.summary = payload.summary
    if payload.category is not None:
        art.category = payload.category
    if payload.body is not None:
        art.body = payload.body
    if payload.author_byline is not None:
        art.author_byline = payload.author_byline
    if payload.scope_note is not None:
        art.scope_note = payload.scope_note
    if payload.sources is not None:
        art.sources_json = json.dumps(
            [s.model_dump(exclude_none=True) for s in payload.sources], ensure_ascii=False
        )
    if payload.review_record is not None:
        art.review_record_json = json.dumps(
            payload.review_record.model_dump(exclude_none=True), ensure_ascii=False
        )

    now = clock.now()
    art.revision += 1
    art.updated_at = now

    db.add(
        ArticleRevision(
            article_id=art.id,
            editor_id=editor.id,
            revision=art.revision,
            title=art.title,
            body=art.body,
            sources_json=art.sources_json,
            review_record_json=art.review_record_json,
            created_at=now,
        )
    )
    sync_article_fts(db, art)
    db.commit()
    db.refresh(art)
    return {
        **serialize_article_detail(art, viewer_bookmarked=False),
        "editor_id": art.editor_id,
        "created_at": _iso_utc(art.created_at),
    }


def editor_publish_article(
    db: Session,
    editor: User,
    article_id: str,
    payload: PublishArticleRequest | None,
    clock: Clock,
) -> dict:
    art = db.scalar(select(Article).where(Article.id == article_id))
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在")

    # Resolve & validate sources
    if payload is not None and payload.sources is not None:
        validated_sources = payload.sources
    else:
        raw_sources = _parse_sources(art.sources_json)
        try:
            validated_sources = [SourceItem.model_validate(item) for item in raw_sources]
        except Exception as exc:
            raise AppError(422, "INVALID_SOURCES", "科普来源链接校验未通过") from exc

    if len(validated_sources) < 1:
        raise AppError(422, "SOURCES_REQUIRED", "发布科普文章必须至少附带一条有效参考来源")

    # Resolve & validate review_record
    if payload is not None and payload.review_record is not None:
        validated_review = payload.review_record
    else:
        raw_review = _parse_review_record(art.review_record_json)
        if not raw_review:
            raise AppError(422, "REVIEW_REQUIRED", "发布科普文章必须提供完整的内容审核记录")
        try:
            validated_review = ReviewRecord.model_validate(raw_review)
        except Exception as exc:
            raise AppError(422, "INVALID_REVIEW_RECORD", "内容审核记录不合法") from exc

    now = clock.now()
    art.sources_json = json.dumps(
        [s.model_dump(exclude_none=True) for s in validated_sources], ensure_ascii=False
    )
    art.review_record_json = json.dumps(
        validated_review.model_dump(exclude_none=True), ensure_ascii=False
    )
    art.status = "published"
    art.published_at = now
    art.updated_at = now

    sync_article_fts(db, art)
    db.commit()
    db.refresh(art)
    return {
        **serialize_article_detail(art, viewer_bookmarked=False),
        "editor_id": art.editor_id,
        "created_at": _iso_utc(art.created_at),
    }


def editor_unpublish_article(db: Session, article_id: str, clock: Clock) -> dict:
    art = db.scalar(select(Article).where(Article.id == article_id))
    if art is None:
        raise AppError(404, "ARTICLE_NOT_FOUND", "科普文章不存在")

    art.status = "unpublished"
    art.updated_at = clock.now()
    sync_article_fts(db, art)
    db.commit()
    db.refresh(art)
    return {
        **serialize_article_detail(art, viewer_bookmarked=False),
        "editor_id": art.editor_id,
        "created_at": _iso_utc(art.created_at),
    }
