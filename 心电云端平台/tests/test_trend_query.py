"""Exercise the production query with both offset timestamps and index updates."""
import json
import sqlite3
import unittest

from health_routes import TREND_INDEX, TREND_INDEX_SQL, TREND_QUERY


class TrendQueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE sessions(id TEXT PRIMARY KEY,owner_id TEXT,complete INTEGER,
                                  metadata TEXT,sample_count INTEGER);
            CREATE TABLE session_details(session_id TEXT PRIMARY KEY,trashed_at TEXT);
            CREATE TABLE measurement_summaries(session_id TEXT PRIMARY KEY,details TEXT);
        ''')
        self.params = ('alice', '2026-11-24T16:00:00+00:00', '2026-11-25T16:00:00+00:00')

    def add(self, sid, stamp, owner='alice', complete=1, source='serial'):
        self.db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',
                        (sid, owner, complete, json.dumps(dict(source=source, started_utc=stamp)), 360))

    def rows(self):
        return sorted(self.db.execute(TREND_QUERY, self.params).fetchall())

    def test_index_preserves_half_open_offset_boundaries_and_scope(self):
        for sid, stamp in [('start', '2026-11-25T00:00:00+08:00'),
                           ('equivalent', '2026-11-24T11:00:00-05:00'),
                           ('before', '2026-11-24T15:59:59Z'),
                           ('end', '2026-11-26T00:00:00+08:00')]:
            self.add(sid, stamp)
        for sid, kwargs in [('other', {'owner':'bob'}), ('pending', {'complete':0}),
                            ('demo', {'source':'demo'}), ('trash', {})]:
            self.add(sid, '2026-11-25T00:00:00Z', **kwargs)
        self.db.execute("INSERT INTO session_details VALUES('trash','2026-11-26')")
        before = self.rows()
        self.assertEqual(len(before), 2)
        self.db.execute(TREND_INDEX_SQL)
        self.db.execute(TREND_INDEX_SQL)  # Existing databases can reopen safely.
        self.assertEqual(self.rows(), before)
        plan = ' '.join(row[3] for row in self.db.execute('EXPLAIN QUERY PLAN '+TREND_QUERY, self.params))
        self.assertIn(TREND_INDEX, plan)
        self.assertIn('<expr>>?', plan)
        self.assertIn('<expr><?', plan)

    def test_mutations_are_visible_without_rebuilding_or_stale_cache(self):
        self.db.execute(TREND_INDEX_SQL)
        self.add('new', '2026-11-25T00:00:00Z', complete=0)
        self.assertEqual(self.rows(), [])
        self.db.execute("UPDATE sessions SET complete=1 WHERE id='new'")
        self.assertEqual(len(self.rows()), 1)
        self.db.execute("UPDATE sessions SET owner_id='bob' WHERE id='new'")
        self.assertEqual(self.rows(), [])
        self.db.execute("UPDATE sessions SET owner_id='alice' WHERE id='new'")
        self.db.execute("INSERT INTO session_details VALUES('new','2026-11-25')")
        self.assertEqual(self.rows(), [])
        self.db.execute("UPDATE session_details SET trashed_at=NULL WHERE session_id='new'")
        self.assertEqual(len(self.rows()), 1)
        self.db.execute("UPDATE sessions SET metadata=? WHERE id='new'",
                        (json.dumps(dict(source='serial', started_utc='2026-11-26T00:00:00Z')),))
        self.assertEqual(self.rows(), [])


if __name__ == '__main__':
    unittest.main()
