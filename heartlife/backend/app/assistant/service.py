from __future__ import annotations

from datetime import timedelta
import re
import time
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.assistant.providers import (
    DeterministicGroundedProvider,
    LLMProvider,
    ProviderResult,
)
from app.assistant.schemas import AssistantChatRequest
from app.core.clock import Clock, user_local_date
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    Article,
    AssistantAuditLog,
    Checkin,
    JournalEntry,
    Plan,
    PlanVersion,
    User,
)

EMERGENCY_KEYWORDS = (
    "胸痛",
    "胸口压榨",
    "呼吸困难",
    "晕厥",
    "昏迷",
    "大汗淋漓",
    "心梗",
    "自杀",
    "自残",
    "不想活",
)

MEDICAL_REFUSAL_KEYWORDS = (
    "确诊",
    "是什么病",
    "开什么药",
    "吃什么药",
    "吃几片",
    "多少毫克",
    "剂量",
    "停药",
    "减药",
    "室早怎么治",
    "房颤吃什么",
    "心电图波形",
    "s波",
    "v波",
    "患病概率",
)

SECURITY_REFUSAL_KEYWORDS = (
    "ignore previous",
    "system prompt",
    "api_key",
    "secret",
    "database_url",
    "drop table",
    "delete from",
    "修改数据库",
    "读取其他用户",
    "user_id=",
)

ASSISTANT_DISCLAIMER = (
    "本回答基于站内已审核健康科普与您本人授权的统计摘要生成，仅供参考，不构成医疗诊断或处方建议。"
)

_QUESTION_FILLER_RE = re.compile(
    r"(请问|怎么调整|怎么办|怎么|如何|有哪些|是什么|可以吗|好不好|为什么|需要注意什么|呢|吗|吧|呀)"
)
_ALNUM_RE = re.compile(r"[a-zA-Z0-9]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_REF_MARKER_RE = re.compile(r"\[ref:([^\]]+)\]")

_CJK_STOP_BIGRAMS = {
    "怎么",
    "如何",
    "什么",
    "请问",
    "可以",
    "能够",
    "需要",
    "应该",
    "是否",
    "哪些",
    "调整",
    "建议",
    "方法",
    "问题",
    "注意",
    "关于",
    "一下",
    "一点",
    "如果",
    "因为",
    "所以",
    "日常",
    "健康",
    "绝密",
    "密词",
}


def _classify_safety_guardrail(query: str) -> tuple[str, str] | None:
    lowered = query.lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw in lowered:
            return (
                "emergency_guidance",
                "检测到可能涉及紧急健康风险的表述。本助手不提供急症评估或医疗监护，请立即拨打当地急救电话（如 120）或由家人陪同前往就近医院急诊科就诊。",
            )
    for kw in MEDICAL_REFUSAL_KEYWORDS:
        if kw in lowered:
            return (
                "medical_refusal",
                "心伴助手仅提供日常健康生活习惯建议与已审核科普检索，无法进行疾病诊断、心电波形判读或提供处方与用药剂量建议。请携带日常记录前往正规医院心血管内科咨询专业医生。",
            )
    for kw in SECURITY_REFUSAL_KEYWORDS:
        if kw in lowered:
            return (
                "security_refusal",
                "仅支持只读查询您本人授权的统计摘要及公开审核科普，不支持修改数据或访问系统敏感配置。",
            )
    return None


def search_published_articles(db: Session, query: str, limit: int = 3) -> list[dict]:
    """Read-only whitelisted search strictly over Article.status == 'published'."""
    raw = query.strip()
    if not raw:
        return []

    core_phrase = _QUESTION_FILLER_RE.sub(" ", raw).strip()
    alnum_tokens = [t.lower() for t in _ALNUM_RE.findall(raw)]

    cjk_bigrams: list[str] = []
    for run in _CJK_RUN_RE.findall(core_phrase or raw):
        if len(run) <= 4 and run not in _CJK_STOP_BIGRAMS:
            cjk_bigrams.append(run)
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in _CJK_STOP_BIGRAMS and bg not in cjk_bigrams:
                cjk_bigrams.append(bg)

    fts_hit_ids: set[str] = set()
    fts_terms = (alnum_tokens + cjk_bigrams)[:8]
    if fts_terms:
        expr = " OR ".join(f'"{t}"' for t in fts_terms)
        try:
            rows = db.execute(
                text(
                    """
                    SELECT f.article_id
                    FROM articles_fts f
                    JOIN articles a ON a.id = f.article_id
                    WHERE a.status = 'published' AND articles_fts MATCH :expr
                    """
                ),
                {"expr": expr},
            ).scalars().all()
            fts_hit_ids.update(rows)
        except Exception:
            pass

    published_articles = db.scalars(
        select(Article).where(Article.status == "published")
    ).all()

    scored: list[tuple[int, Article]] = []
    for art in published_articles:
        title_l = art.title.lower()
        summary_l = art.summary.lower()
        cat_l = art.category.lower()
        body_l = art.body.lower()
        haystack = f"{title_l}\n{summary_l}\n{cat_l}\n{body_l}"

        # If query explicitly includes alphanumeric identifiers (e.g. code/tag), require at least one match
        if alnum_tokens and not any(tok in haystack for tok in alnum_tokens):
            continue

        score = 0
        if art.id in fts_hit_ids:
            score += 3

        if len(raw) >= 2 and raw.lower() in haystack:
            score += 10
        if core_phrase and len(core_phrase) >= 2 and core_phrase.lower() in haystack:
            score += 8

        for tok in alnum_tokens:
            if tok in title_l:
                score += 6
            elif tok in haystack:
                score += 4

        for term in cjk_bigrams:
            if term in title_l:
                score += 4
            elif term in cat_l or term in summary_l:
                score += 3
            elif term in body_l:
                score += 2

        if score >= 4:
            scored.append((score, art))

    scored.sort(key=lambda item: (item[0], item[1].published_at or item[1].created_at), reverse=True)
    return [
        {
            "id": art.id,
            "title": art.title,
            "category": art.category,
            "summary": art.summary,
            "body_excerpt": art.body[:240],
        }
        for _, art in scored[:limit]
    ]


def build_sanitized_weekly_summary(
    db: Session, current_user: User, clock: Clock
) -> dict:
    """Strictly numeric weekly summary bound to current_user.id (never exposes notes, tags, or credentials)."""
    today_local = user_local_date(clock, current_user.timezone)
    monday = today_local - timedelta(days=today_local.weekday())
    observed_days = (today_local - monday).days + 1

    journals = db.scalars(
        select(JournalEntry).where(
            JournalEntry.user_id == current_user.id,
            JournalEntry.local_date >= monday,
            JournalEntry.local_date <= today_local,
        )
    ).all()

    sleep_vals = [j.sleep_minutes for j in journals if j.sleep_minutes is not None]
    act_vals = [j.activity_minutes for j in journals if j.activity_minutes is not None]

    sleep_mean: int | float | None = None
    if sleep_vals:
        avg = round(sum(sleep_vals) / len(sleep_vals), 1)
        sleep_mean = int(avg) if avg.is_integer() else avg

    plans = db.scalars(select(Plan).where(Plan.owner_id == current_user.id)).all()
    plan_ids = [p.id for p in plans]

    plans_due = 0
    plans_completed = 0
    if plan_ids:
        versions = db.scalars(
            select(PlanVersion)
            .where(PlanVersion.plan_id.in_(plan_ids))
            .order_by(PlanVersion.version_num.desc())
        ).all()
        versions_by_plan: dict[str, list[PlanVersion]] = {}
        for pv in versions:
            versions_by_plan.setdefault(pv.plan_id, []).append(pv)

        checkins = db.scalars(
            select(Checkin).where(
                Checkin.plan_id.in_(plan_ids),
                Checkin.local_date >= monday,
                Checkin.local_date <= today_local,
                Checkin.completed.is_(True),
            )
        ).all()
        completed_set = {(c.plan_id, c.local_date) for c in checkins}

        for day_offset in range(observed_days):
            d = monday + timedelta(days=day_offset)
            day_bit = 1 << d.weekday()
            for p in plans:
                p_versions = versions_by_plan.get(p.id, [])
                effective_pv: PlanVersion | None = None
                for pv in p_versions:
                    if pv.effective_from <= d and (pv.effective_to is None or d <= pv.effective_to):
                        effective_pv = pv
                        break
                if effective_pv is None or not effective_pv.active:
                    continue
                if d < effective_pv.start_date:
                    continue
                if effective_pv.end_date is not None and d > effective_pv.end_date:
                    continue
                if (effective_pv.weekday_mask & day_bit) == 0:
                    continue
                plans_due += 1
                if (p.id, d) in completed_set:
                    plans_completed += 1

    completion_rate = round(plans_completed / plans_due, 4) if plans_due > 0 else None

    return {
        "week_start": monday.isoformat(),
        "observed_days": observed_days,
        "journal_days": len(journals),
        "sleep_valid_days": len(sleep_vals),
        "sleep_mean_minutes": sleep_mean,
        "activity_valid_days": len(act_vals),
        "activity_total_minutes": sum(act_vals) if act_vals else 0,
        "plans_due": plans_due,
        "plans_completed": plans_completed,
        "completion_rate": completion_rate,
    }


def build_sanitized_plans_summary(db: Session, current_user: User) -> list[dict]:
    plans = db.scalars(
        select(Plan)
        .where(Plan.owner_id == current_user.id)
        .order_by(Plan.created_at.asc())
    ).all()
    return [{"title": p.title, "active": p.active} for p in plans]


def _verify_grounding(
    result: ProviderResult,
    *,
    allowed_ids: set[str],
    has_retrieved_articles: bool,
    has_personal_context: bool,
    weekly_summary: dict | None,
) -> bool:
    # 1. Reject any citation ID outside retrieved published articles
    for cid in result.cited_ids:
        if cid not in allowed_ids:
            return False

    # 2. Reject unverified inline [ref:...] markers
    for marker_id in _REF_MARKER_RE.findall(result.answer):
        if marker_id.strip() not in allowed_ids:
            return False

    # 3. Require at least one valid citation when answering pure encyclopedia query with retrieved articles
    if has_retrieved_articles and not has_personal_context and len(result.cited_ids) == 0:
        return False

    # 4. Verify reported numbers match deterministic weekly_summary
    if result.reported_numbers is not None:
        if weekly_summary is None:
            return False
        for key, reported_val in result.reported_numbers.items():
            if key not in weekly_summary:
                return False
            expected_val = weekly_summary[key]
            if reported_val is None and expected_val is None:
                continue
            if reported_val is None or expected_val is None:
                return False
            if abs(float(reported_val) - float(expected_val)) > 1e-6:
                return False

    return True


def _record_audit_log(
    db: Session,
    *,
    user_id: str,
    status: str,
    tools_used: list[str],
    cited_ids: list[str],
    started_monotonic: float,
    clock: Clock,
) -> None:
    latency_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
    db.add(
        AssistantAuditLog(
            user_id=user_id,
            status=status,
            tools_used=",".join(tools_used)[:200],
            cited_article_ids=",".join(cited_ids)[:300],
            latency_ms=latency_ms,
            created_at=clock.now(),
        )
    )
    db.commit()


def handle_assistant_chat(
    db: Session,
    *,
    current_user: User,
    payload: AssistantChatRequest,
    settings: Settings,
    clock: Clock,
    override_provider: LLMProvider | None = None,
) -> dict:
    if not settings.is_assistant_available:
        raise AppError(503, "ASSISTANT_DISABLED", "AI 健康生活助手未启用")

    started = time.monotonic()

    # Step 1: Deterministic safety & prompt-injection guardrails
    guard = _classify_safety_guardrail(payload.query)
    if guard is not None:
        mode, msg = guard
        _record_audit_log(
            db,
            user_id=current_user.id,
            status=mode,
            tools_used=[],
            cited_ids=[],
            started_monotonic=started,
            clock=clock,
        )
        return {
            "mode": mode,
            "answer": msg,
            "citations": [],
            "tools_used": [],
            "fallback_url": None,
            "disclaimer": ASSISTANT_DISCLAIMER,
        }

    # Step 2: Read-only whitelisted tools bound strictly to current_user.id & published articles
    tools_used: list[str] = ["search_published_articles"]
    retrieved_articles = search_published_articles(db, payload.query, limit=3)

    weekly_summary: dict | None = None
    if payload.allow_weekly_report:
        tools_used.append("weekly_report")
        weekly_summary = build_sanitized_weekly_summary(db, current_user, clock)

    plans_summary: list[dict] | None = None
    if payload.allow_plans:
        tools_used.append("plans_summary")
        plans_summary = build_sanitized_plans_summary(db, current_user)

    if not retrieved_articles and not payload.allow_weekly_report and not payload.allow_plans:
        _record_audit_log(
            db,
            user_id=current_user.id,
            status="insufficient_evidence",
            tools_used=tools_used,
            cited_ids=[],
            started_monotonic=started,
            clock=clock,
        )
        return {
            "mode": "insufficient_evidence",
            "answer": "当前已审核健康百科中暂无直接匹配的条目，您可前往「健康百科」按分类浏览科普文章。",
            "citations": [],
            "tools_used": tools_used,
            "fallback_url": "/knowledge",
            "disclaimer": ASSISTANT_DISCLAIMER,
        }

    # Step 3: Provider execution & Grounding verifier
    context = {
        "query": payload.query,
        "articles": retrieved_articles,
        "weekly_summary": weekly_summary,
        "plans_summary": plans_summary,
    }
    article_by_id = {a["id"]: a for a in retrieved_articles}
    allowed_ids = set(article_by_id.keys())

    provider: LLMProvider = override_provider or DeterministicGroundedProvider()
    try:
        provider_res = provider.generate(context)
    except TimeoutError:
        det_citations = [
            {
                "id": a["id"],
                "title": a["title"],
                "category": a["category"],
                "summary": a["summary"],
            }
            for a in retrieved_articles
        ]
        _record_audit_log(
            db,
            user_id=current_user.id,
            status="provider_timeout",
            tools_used=tools_used,
            cited_ids=[a["id"] for a in retrieved_articles],
            started_monotonic=started,
            clock=clock,
        )
        return {
            "mode": "provider_timeout",
            "answer": "智能解读连接超时，已为您保留健康百科入口，您可直接查阅已审核科普或健康周报。",
            "citations": det_citations,
            "tools_used": tools_used,
            "fallback_url": "/knowledge",
            "disclaimer": ASSISTANT_DISCLAIMER,
        }

    is_grounded = _verify_grounding(
        provider_res,
        allowed_ids=allowed_ids,
        has_retrieved_articles=bool(retrieved_articles),
        has_personal_context=bool(payload.allow_weekly_report or payload.allow_plans),
        weekly_summary=weekly_summary,
    )

    if is_grounded:
        mode = "grounded"
        final_res = provider_res
    else:
        mode = "verified_fallback"
        final_res = DeterministicGroundedProvider().generate(context)

    seen_cids: list[str] = []
    for cid in final_res.cited_ids:
        if cid in article_by_id and cid not in seen_cids:
            seen_cids.append(cid)

    citations_out = [
        {
            "id": article_by_id[cid]["id"],
            "title": article_by_id[cid]["title"],
            "category": article_by_id[cid]["category"],
            "summary": article_by_id[cid]["summary"],
        }
        for cid in seen_cids
    ]

    _record_audit_log(
        db,
        user_id=current_user.id,
        status=mode,
        tools_used=tools_used,
        cited_ids=seen_cids,
        started_monotonic=started,
        clock=clock,
    )
    return {
        "mode": mode,
        "answer": final_res.answer,
        "citations": citations_out,
        "tools_used": tools_used,
        "fallback_url": None,
        "disclaimer": ASSISTANT_DISCLAIMER,
    }
