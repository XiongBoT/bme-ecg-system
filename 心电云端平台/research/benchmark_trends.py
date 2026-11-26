"""Compare the same read-only trend query before/after indexing synthetic records."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import platform
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from health_routes import TREND_INDEX_SQL, TREND_QUERY


def benchmark(records=40000, repeats=30):
    if not 100 <= records <= 1000000 or not 5 <= repeats <= 1000:
        raise ValueError('records must be 100..1000000; repeats must be 5..1000')
    with sqlite3.connect(':memory:') as db:
        db.executescript('''
            CREATE TABLE sessions(id TEXT PRIMARY KEY,owner_id TEXT,complete INTEGER,
                                  metadata TEXT,sample_count INTEGER);
            CREATE INDEX sessions_owner ON sessions(owner_id);
            CREATE TABLE session_details(session_id TEXT PRIMARY KEY,trashed_at TEXT);
            CREATE TABLE measurement_summaries(session_id TEXT PRIMARY KEY,details TEXT);
        ''')
        first = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.executemany('INSERT INTO sessions VALUES(?,?,?,?,?)',
                       ((str(i), 'owner'+str(i%4), 1,
                         json.dumps(dict(source='serial', started_utc=(first+timedelta(minutes=i*15)).isoformat())),
                         21600) for i in range(records)))
        params = ('owner0', '2026-01-15T16:00:00Z', '2026-01-16T16:00:00Z')
        results = {}
        reference = None
        for label in ('owner_index', 'owner_and_date_index'):
            if label == 'owner_and_date_index':
                started = time.perf_counter()
                db.execute(TREND_INDEX_SQL)
                results['index_build_ms'] = round((time.perf_counter()-started)*1000, 3)
            plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN '+TREND_QUERY, params)]
            timings = []
            for iteration in range(repeats+3):
                started = time.perf_counter()
                rows = sorted(db.execute(TREND_QUERY, params).fetchall())
                elapsed = (time.perf_counter()-started)*1000
                if reference is None:
                    reference = rows
                if rows != reference:
                    raise AssertionError('Index changed query results')
                if iteration >= 3:
                    timings.append(elapsed)
            results[label] = dict(p50_ms=round(statistics.median(timings), 4),
                                  p95_ms=round(sorted(timings)[math.ceil(.95*len(timings))-1], 4),
                                  matched_records=len(reference), query_plan=plan)
        return dict(schema=1, records=records, owners=4, repeats=repeats, warmups=3,
                    python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                    platform=platform.platform(), results_equal=True, results=results,
                    scope='Synthetic in-memory SQLite query only; excludes API, disk IO, TLS and production capacity.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=40000)
    parser.add_argument('--repeats', type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.records, args.repeats), ensure_ascii=False, indent=2))
