from __future__ import annotations

"""HeartLife Local Synthetic Performance Benchmark (PRD §9).

Generates an isolated temporary SQLite database with:
  - 50 synthetic users
  - 1,000 synthetic community posts
  - 10,000 synthetic journal & check-in records
Then executes 20 concurrent virtual users against core read APIs
(/api/v1/posts, /api/v1/articles, /api/v1/me/dashboard, /api/v1/me/weekly-report)
and reports real P50, P95, P99 latencies and 5xx error count.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.security import generate_token, hash_password, hash_token  # noqa: E402
from app.db.database import build_session_factory  # noqa: E402
from app.db.migrations_runner import run_migrations  # noqa: E402
from app.db.models import (  # noqa: E402
    Article,
    Checkin,
    JournalEntry,
    Plan,
    PlanVersion,
    Post,
    User,
    UserSession,
)
from app.main import create_app  # noqa: E402


def run_benchmark(
    num_users: int = 50,
    num_posts: int = 1000,
    num_journals: int = 5000,
    num_checkins: int = 5000,
    concurrency: int = 20,
    requests_per_vu: int = 12,
) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "perf_bench.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        run_migrations(db_url)

        engine, SessionLocal = build_session_factory(db_url)
        now = datetime(2026, 11, 26, 8, 0, 0, tzinfo=timezone.utc)
        today = date(2026, 11, 26)
        pwd_hash = hash_password("BenchPass123!")

        tokens: list[str] = []
        t_seed_start = time.perf_counter()
        with SessionLocal() as db:
            users: list[User] = []
            for i in range(num_users):
                u = User(
                    account=f"perf_user_{i:03d}",
                    password_hash=pwd_hash,
                    nickname=f"压测用户{i:03d}",
                    timezone="Asia/Shanghai",
                    roles="member",
                    status="active",
                    is_demo=True,
                    created_at=now,
                    updated_at=now,
                )
                users.append(u)
            db.add_all(users)
            db.flush()

            # Create active sessions for the first `concurrency` users
            for i in range(concurrency):
                raw_tok = generate_token(24)
                csrf_tok = generate_token(16)
                tokens.append(raw_tok)
                db.add(
                    UserSession(
                        id_hash=hash_token(raw_tok),
                        user_id=users[i].id,
                        csrf_token=csrf_tok,
                        csrf_hash=hash_token(csrf_tok),
                        expires_at=now + timedelta(days=7),
                        created_at=now,
                    )
                )

            # 12 published articles
            cats = ["日常健康", "运动与习惯", "睡眠与休息", "心脏健康科普交流", "设备使用经验"]
            for i in range(12):
                db.add(
                    Article(
                        slug=f"bench-art-{i}",
                        editor_id=users[0].id,
                        status="published",
                        title=f"合成基准科普文章 {i}",
                        summary="用于本地性能评测的合成科普摘要",
                        category="日常健康",
                        body="合成科普正文 " * 20,
                        sources_json=json.dumps([{"title": "WHO", "url": "https://www.who.int"}]),
                        review_record_json=json.dumps({"reviewer": "bench", "review_type": "课程内容审核", "reviewed_at": "2026-11-26"}),
                        is_demo=True,
                        published_at=now - timedelta(minutes=i),
                        created_at=now,
                        updated_at=now,
                    )
                )

            # 1,000 posts
            posts_batch = [
                Post(
                    author_id=users[i % num_users].id,
                    category=cats[i % len(cats)],
                    title=f"合成测试帖 #{i} 规律作息与散步打卡",
                    body="这是一条合成压测社区内容，不包含任何真实用户健康数据。" * 3,
                    status="visible",
                    is_demo=True,
                    created_at=now - timedelta(seconds=i),
                    updated_at=now - timedelta(seconds=i),
                )
                for i in range(num_posts)
            ]
            db.add_all(posts_batch)

            # 5,000 journals (50 users * 100 days)
            journals_batch = []
            days_per_user = max(1, num_journals // num_users)
            for u in users:
                for d_off in range(days_per_user):
                    journals_batch.append(
                        JournalEntry(
                            user_id=u.id,
                            local_date=today - timedelta(days=d_off),
                            sleep_minutes=420 + (d_off % 60),
                            activity_minutes=20 + (d_off % 30),
                            mood="good",
                            symptom_tags_json="[]",
                            is_demo=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            db.add_all(journals_batch)

            # Plans + 5,000 checkins
            plans: list[Plan] = []
            for u in users:
                p = Plan(
                    owner_id=u.id,
                    title="每日散步习惯",
                    active=True,
                    is_demo=True,
                    created_at=now,
                    updated_at=now,
                )
                plans.append(p)
            db.add_all(plans)
            db.flush()

            versions_batch = []
            checkins_batch = []
            chk_days = max(1, num_checkins // num_users)
            for p in plans:
                start_d = today - timedelta(days=chk_days + 5)
                versions_batch.append(
                    PlanVersion(
                        plan_id=p.id,
                        version_num=1,
                        effective_from=start_d,
                        weekday_mask=127,
                        active=True,
                        start_date=start_d,
                        created_at=now,
                    )
                )
                for d_off in range(chk_days):
                    checkins_batch.append(
                        Checkin(
                            plan_id=p.id,
                            local_date=today - timedelta(days=d_off),
                            completed=True,
                            updated_at=now,
                        )
                    )
            db.add_all(versions_batch)
            db.add_all(checkins_batch)
            db.commit()
        seed_elapsed = time.perf_counter() - t_seed_start

        settings = Settings(database_url=db_url, app_env="test", demo_mode=True)
        app = create_app(settings=settings)

        endpoints = [
            "/api/v1/posts?limit=20",
            "/api/v1/articles?limit=10",
            "/api/v1/me/dashboard",
            "/api/v1/me/weekly-report",
        ]

        latencies_ms: list[float] = []
        status_5xx = 0
        status_ok = 0

        with TestClient(app) as base_client:
            def worker(vu_idx: int) -> tuple[list[float], int, int]:
                local_lats: list[float] = []
                ok_cnt = 0
                err_5xx = 0
                tok = tokens[vu_idx]
                for step in range(requests_per_vu):
                    ep = endpoints[step % len(endpoints)]
                    t0 = time.perf_counter()
                    resp = base_client.get(ep, cookies={"hl_session": tok})
                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    local_lats.append(dt_ms)
                    if resp.status_code >= 500:
                        err_5xx += 1
                    elif 200 <= resp.status_code < 300:
                        ok_cnt += 1
                return local_lats, ok_cnt, err_5xx

            t_run_start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(worker, i) for i in range(concurrency)]
                for f in futures:
                    lats, ok_c, e5 = f.result()
                    latencies_ms.extend(lats)
                    status_ok += ok_c
                    status_5xx += e5
            run_elapsed = time.perf_counter() - t_run_start

        engine.dispose()

        latencies_ms.sort()
        total = len(latencies_ms)
        p50 = latencies_ms[int(total * 0.50)]
        p95 = latencies_ms[min(total - 1, int(total * 0.95))]
        p99 = latencies_ms[min(total - 1, int(total * 0.99))]

        result = {
            "machine": {
                "os": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
            },
            "dataset": {
                "users": num_users,
                "posts": num_posts,
                "journals": len(journals_batch),
                "checkins": len(checkins_batch),
                "seed_seconds": round(seed_elapsed, 2),
            },
            "workload": {
                "concurrent_vus": concurrency,
                "requests_per_vu": requests_per_vu,
                "total_requests": total,
                "endpoints": endpoints,
                "elapsed_seconds": round(run_elapsed, 2),
            },
            "metrics": {
                "ok_2xx": status_ok,
                "errors_5xx": status_5xx,
                "mean_ms": round(statistics.mean(latencies_ms), 2),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2),
                "target_p95_lte_500ms": p95 <= 500.0 and status_5xx == 0,
            },
        }
        return result


if __name__ == "__main__":
    summary = run_benchmark()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
