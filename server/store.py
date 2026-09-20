"""Small single-instance SQLite store; transactions never contain network I/O."""
import json
import os
from pathlib import Path
import sqlite3
from cloud import domain


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / 'workspace.sqlite3'
        db = self.connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS mailbox(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
            db.commit()
        finally:
            db.close()
        os.chmod(self.path,0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def mutate(self, operation):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM mailbox WHERE id=1').fetchone()
            state = json.loads(row[0]) if row else domain.initial()
            output = operation(state)
            value = json.dumps(state,ensure_ascii=False)
            if len(value.encode()) > 3000000:
                raise domain.Rejected('Mailbox capacity')
            db.execute('INSERT OR REPLACE INTO mailbox(id,value) VALUES(1,?)',(value,))
            db.commit()
            return output
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
