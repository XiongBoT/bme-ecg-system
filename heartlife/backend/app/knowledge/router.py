from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.deps import (
    get_clock,
    get_current_user,
    get_db,
    get_optional_user,
    require_role,
)
from app.db.models import User
from app.knowledge.schemas import (
    CreateArticleRequest,
    PublishArticleRequest,
    UpdateArticleRequest,
)
from app.knowledge.service import (
    clear_reading_history,
    editor_create_article,
    editor_get_article,
    editor_list_articles,
    editor_publish_article,
    editor_unpublish_article,
    editor_update_article,
    get_published_article_detail,
    list_article_bookmarks,
    list_article_categories,
    list_published_articles,
    list_reading_history,
    remove_article_bookmark,
    set_article_bookmark,
    upsert_reading_history,
)

router = APIRouter(tags=["knowledge"])


@router.get("/articles/categories")
def api_list_article_categories(db: Session = Depends(get_db)) -> dict:
    cats = list_article_categories(db)
    return {"categories": cats}


@router.get("/articles")
def api_list_articles(
    category: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120),
    cursor: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_optional_user),
) -> dict:
    return list_published_articles(
        db,
        category=category,
        q=q,
        cursor=cursor,
        limit=limit,
        viewer=viewer,
    )


@router.get("/articles/{article_id}")
def api_get_article_detail(
    article_id: str,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_optional_user),
) -> dict:
    return get_published_article_detail(db, article_id, viewer=viewer)


@router.put("/articles/{article_id}/bookmark")
def api_bookmark_article(
    article_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return set_article_bookmark(db, user, article_id, clock)


@router.delete("/articles/{article_id}/bookmark")
def api_unbookmark_article(
    article_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return remove_article_bookmark(db, user, article_id)


@router.get("/me/article-bookmarks")
def api_list_my_article_bookmarks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_article_bookmarks(db, user)


@router.put("/me/reading-history/{article_id}")
def api_record_reading_history(
    article_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return upsert_reading_history(db, user, article_id, clock)


@router.get("/me/reading-history")
def api_get_reading_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_reading_history(db, user)


@router.delete("/me/reading-history")
def api_clear_reading_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return clear_reading_history(db, user)


# ---------------- Editor Endpoints ----------------


@router.get("/editor/articles")
def api_editor_list_articles(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    _editor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    return editor_list_articles(db, status_filter=status_filter)


@router.get("/editor/articles/{article_id}")
def api_editor_get_article(
    article_id: str,
    _editor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    return editor_get_article(db, article_id)


@router.post("/editor/articles", status_code=status.HTTP_201_CREATED)
def api_editor_create_article(
    payload: CreateArticleRequest,
    editor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return editor_create_article(db, editor, payload, clock)


@router.patch("/editor/articles/{article_id}")
def api_editor_update_article(
    article_id: str,
    payload: UpdateArticleRequest,
    editor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return editor_update_article(db, editor, article_id, payload, clock)


@router.post("/editor/articles/{article_id}/publish")
def api_editor_publish_article(
    article_id: str,
    payload: PublishArticleRequest | None = Body(default=None),
    editor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return editor_publish_article(db, editor, article_id, payload, clock)


@router.post("/editor/articles/{article_id}/unpublish")
def api_editor_unpublish_article(
    article_id: str,
    _editor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return editor_unpublish_article(db, article_id, clock)
