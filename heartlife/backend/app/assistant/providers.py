from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ProviderResult:
    answer: str
    cited_ids: list[str]
    reported_numbers: dict[str, float | int | None] | None = None


class LLMProvider(Protocol):
    def generate(self, context: dict) -> ProviderResult:
        ...


class DeterministicGroundedProvider:
    """Deterministic local synthesizer strictly grounded in retrieved published articles and sanitized stats."""

    def generate(self, context: dict) -> ProviderResult:
        articles: list[dict] = context.get("articles") or []
        weekly_summary: dict | None = context.get("weekly_summary")
        plans_summary: list[dict] | None = context.get("plans_summary")

        parts: list[str] = []
        cited_ids: list[str] = []

        if articles:
            lines = ["结合站内已审核健康百科，为您提供以下日常健康参考："]
            for art in articles:
                cited_ids.append(art["id"])
                lines.append(f"• 《{art['title']}》（{art['category']}）：{art['summary']}")
            parts.append("\n".join(lines))

        reported_nums: dict[str, float | int | None] | None = None
        if weekly_summary is not None:
            reported_nums = {
                "journal_days": weekly_summary["journal_days"],
                "sleep_valid_days": weekly_summary["sleep_valid_days"],
                "sleep_mean_minutes": weekly_summary["sleep_mean_minutes"],
                "activity_total_minutes": weekly_summary["activity_total_minutes"],
                "plans_due": weekly_summary["plans_due"],
                "plans_completed": weekly_summary["plans_completed"],
            }
            stat_bits = [
                f"本周（自 {weekly_summary['week_start']} 起共观察 {weekly_summary['observed_days']} 天）"
                f"已记录日记 {weekly_summary['journal_days']} 天"
            ]
            if weekly_summary["sleep_mean_minutes"] is not None:
                stat_bits.append(
                    f"有效睡眠记录 {weekly_summary['sleep_valid_days']} 天，平均睡眠时长 {weekly_summary['sleep_mean_minutes']} 分钟"
                )
            else:
                stat_bits.append("暂无睡眠时长记录")
            stat_bits.append(f"累计日常活动 {weekly_summary['activity_total_minutes']} 分钟")
            if weekly_summary["plans_due"] > 0:
                stat_bits.append(
                    f"习惯打卡完成 {weekly_summary['plans_completed']}/{weekly_summary['plans_due']} 次"
                )
            parts.append("您本人授权的本周统计摘要：" + "，".join(stat_bits) + "。")

        if plans_summary is not None:
            active_titles = [p["title"] for p in plans_summary if p.get("active")]
            if active_titles:
                parts.append("当前进行中的习惯计划：" + "、".join(active_titles) + "。")
            else:
                parts.append("当前暂无启用中的习惯计划。")

        if not parts:
            parts.append("当前已审核健康百科中暂无直接匹配的条目，您可前往「健康百科」按分类浏览科普文章。")

        return ProviderResult(
            answer="\n\n".join(parts),
            cited_ids=cited_ids,
            reported_numbers=reported_nums,
        )
