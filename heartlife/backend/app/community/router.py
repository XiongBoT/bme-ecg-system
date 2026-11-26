from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.community.schemas import (
    COMMUNITY_CATEGORIES,
    CreateCommentRequest,
    CreatePostRequest,
    CreateReportRequest,
    ModerationReasonRequest,
    ResolveReportRequest,
    UpdatePostRequest,
)
from app.community.service import (
    add_bookmark,
    block_user,
    create_comment,
    create_post,
    create_report,
    delete_comment,
    delete_post,
    follow_category,
    get_post_detail,
    like_post,
    list_followed_categories,
    list_moderation_actions,
    list_moderation_reports,
    list_my_blocks,
    list_my_bookmarks,
    list_my_posts,
    list_post_comments,
    list_posts,
    moderate_hide_content,
    moderate_restore_content,
    remove_bookmark,
    resolve_moderation_report,
    unblock_user,
    unfollow_category,
    unlike_post,
    update_post,
)
from app.core.clock import Clock
from app.core.deps import (
    get_clock,
    get_current_user,
    get_db,
    get_optional_user,
    require_role,
)
from app.db.models import User

router = APIRouter(tags=["community"])


@router.get("/community/categories")
def api_list_categories() -> dict:
    return {"categories": list(COMMUNITY_CATEGORIES)}


@router.post("/posts", status_code=status.HTTP_201_CREATED)
def api_create_post(
    payload: CreatePostRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return create_post(db, current_user, payload, clock)


@router.get("/posts")
def api_list_posts(
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    followed_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_posts(
        db,
        viewer=viewer,
        category=category,
        tag=tag,
        q=q,
        followed_only=followed_only,
        cursor=cursor,
        limit=limit,
    )


@router.get("/posts/{post_id}")
def api_get_post(
    post_id: str,
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    return get_post_detail(db, post_id, viewer)


@router.get("/me/posts")
def api_list_my_posts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_my_posts(db, current_user)


@router.patch("/posts/{post_id}")
def api_update_post(
    post_id: str,
    payload: UpdatePostRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return update_post(db, post_id, current_user, payload, clock)


@router.delete("/posts/{post_id}")
def api_delete_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return delete_post(db, post_id, current_user, clock)


@router.put("/posts/{post_id}/like")
def api_like_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return like_post(db, post_id, current_user, clock)


@router.delete("/posts/{post_id}/like")
def api_unlike_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return unlike_post(db, post_id, current_user)


@router.put("/bookmarks/{target_type}/{target_id}")
def api_add_bookmark(
    target_type: str,
    target_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return add_bookmark(db, target_type, target_id, current_user, clock)


@router.delete("/bookmarks/{target_type}/{target_id}")
def api_remove_bookmark(
    target_type: str,
    target_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return remove_bookmark(db, target_type, target_id, current_user)


@router.get("/me/bookmarks")
def api_list_my_bookmarks(
    target_type: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_my_bookmarks(db, current_user, target_type=target_type)


@router.get("/posts/{post_id}/comments")
def api_list_comments(
    post_id: str,
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_post_comments(db, post_id, viewer)


@router.post("/posts/{post_id}/comments", status_code=status.HTTP_201_CREATED)
def api_create_comment(
    post_id: str,
    payload: CreateCommentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return create_comment(db, post_id, current_user, payload, clock)


@router.delete("/comments/{comment_id}")
def api_delete_comment(
    comment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return delete_comment(db, comment_id, current_user, clock)


@router.put("/me/blocks/{blocked_id}")
def api_block_user(
    blocked_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return block_user(db, current_user, blocked_id, clock)


@router.delete("/me/blocks/{blocked_id}")
def api_unblock_user(
    blocked_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return unblock_user(db, current_user, blocked_id)


@router.get("/me/blocks")
def api_list_blocks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_my_blocks(db, current_user)


@router.put("/me/follows/categories/{category}")
def api_follow_category(
    category: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return follow_category(db, current_user, category, clock)


@router.delete("/me/follows/categories/{category}")
def api_unfollow_category(
    category: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return unfollow_category(db, current_user, category)


@router.get("/me/follows/categories")
def api_list_followed_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return list_followed_categories(db, current_user)


@router.post("/reports", status_code=status.HTTP_201_CREATED)
def api_create_report(
    payload: CreateReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return create_report(db, current_user, payload, clock)


@router.get("/moderation/reports")
def api_list_moderation_reports(
    status: str | None = "pending",
    _moderator: User = Depends(require_role("moderator")),
    db: Session = Depends(get_db),
) -> dict:
    return list_moderation_reports(db, status_filter=status)


@router.post("/moderation/reports/{report_id}/resolve")
def api_resolve_moderation_report(
    report_id: str,
    payload: ResolveReportRequest,
    moderator: User = Depends(require_role("moderator")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return resolve_moderation_report(db, report_id, moderator, payload, clock)


@router.post("/moderation/content/{target_type}/{target_id}/hide")
def api_moderate_hide_content(
    target_type: str,
    target_id: str,
    payload: ModerationReasonRequest,
    moderator: User = Depends(require_role("moderator")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return moderate_hide_content(db, target_type, target_id, moderator, payload, clock)


@router.post("/moderation/content/{target_type}/{target_id}/restore")
def api_moderate_restore_content(
    target_type: str,
    target_id: str,
    payload: ModerationReasonRequest,
    moderator: User = Depends(require_role("moderator")),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict:
    return moderate_restore_content(db, target_type, target_id, moderator, payload, clock)


@router.get("/moderation/actions")
def api_list_moderation_actions(
    target_type: str | None = None,
    target_id: str | None = None,
    _moderator: User = Depends(require_role("moderator")),
    db: Session = Depends(get_db),
) -> dict:
    return list_moderation_actions(db, target_type=target_type, target_id=target_id)
