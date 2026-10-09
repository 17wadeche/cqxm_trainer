import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from models import EvidenceSource
from config import PROCEDURES
class Repository:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "gch.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sources (
          id TEXT PRIMARY KEY, docid TEXT NOT NULL, kind TEXT NOT NULL,
          active INTEGER NOT NULL, payload TEXT NOT NULL, warnings TEXT NOT NULL,
          created TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
          source_id UNINDEXED, chunk_id UNINDEXED, locator UNINDEXED, text,
          tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS source_origins (
          source_id TEXT PRIMARY KEY, origin TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS default_initializations (
          docid TEXT PRIMARY KEY
        );
        """)
    def _put(self, source, warnings, origin):
        if source.kind == "procedure":
            self.db.execute("UPDATE sources SET active=0 WHERE docid=? AND kind='procedure'", (source.document_id,))
        self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)", (
            source.id, source.document_id, source.kind, 1,
            source.model_dump_json(), json.dumps(warnings), datetime.now(timezone.utc).isoformat()))
        self.db.execute("INSERT INTO source_origins VALUES (?,?)", (source.id, origin))
        self.db.executemany("INSERT INTO chunks VALUES (?,?,?,?)", [
            (source.id, c.id, c.locator, c.text) for c in source.chunks])
    def put(self, source, warnings):
        with self.lock, self.db:
            self._put(source, warnings, 'uploaded')
    def defaults_pending(self):
        with self.lock:
            initialized={r[0] for r in self.db.execute('SELECT docid FROM default_initializations')}
            existing={r[0] for r in self.db.execute("SELECT docid FROM sources WHERE kind='procedure'")}
        return {docid for docid,_ in PROCEDURES} - initialized - existing
    def install_defaults(self, entries):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                pending=self.defaults_pending()
                for source,warnings in entries:
                    if source.document_id in pending:
                        self._put(source,warnings,'bundled')
                        self.db.execute('INSERT INTO default_initializations VALUES (?)',(source.document_id,))
                        pending.remove(source.document_id)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
    def active_procedures(self):
        permitted = [document_id for document_id, _ in PROCEDURES]
        placeholders = ','.join('?' for _ in permitted)
        with self.lock:
            rows = self.db.execute(
                f"SELECT payload,warnings FROM sources WHERE kind='procedure' AND active=1 AND docid IN ({placeholders}) ORDER BY docid",
                permitted).fetchall()
        return [(EvidenceSource.model_validate_json(r['payload']), json.loads(r['warnings'])) for r in rows]
    def catalog(self):
        with self.lock:
            origins=dict(self.db.execute('SELECT source_id,origin FROM source_origins').fetchall())
        return [{"id": s.id, "document_id": s.document_id, "name": s.name,
                 "revision": s.revision, "chunks": len(s.chunks), "warnings": w,
                 "origin": origins.get(s.id,'uploaded')}
                for s, w in self.active_procedures()]
    def remove(self, source_id):
        with self.lock, self.db:
            row=self.db.execute("SELECT docid FROM sources WHERE id=? AND kind='procedure'",(source_id,)).fetchone()
            if row:
                self.db.execute('INSERT OR IGNORE INTO default_initializations VALUES (?)',(row['docid'],))
            self.db.execute('DELETE FROM source_origins WHERE source_id=?',(source_id,))
            self.db.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
            self.db.execute("DELETE FROM sources WHERE id=?", (source_id,))
    def search(self, query, source_ids, limit=6):
        if not source_ids:
            return []
        terms = list(dict.fromkeys(re.findall(r"[\w-]{3,}", query.lower())))[:18]
        if not terms:
            return []
        match = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
        marks = ",".join("?" for _ in source_ids)
        with self.lock:
            rows = self.db.execute(
                f"SELECT source_id,chunk_id,locator,text FROM chunks WHERE chunks MATCH ? AND source_id IN ({marks}) ORDER BY bm25(chunks) LIMIT ?",
                (match, *source_ids, min(max(int(limit), 1), 8))).fetchall()
        return [dict(r) for r in rows]