"""Small single-instance SQLite store; transactions never contain network I/O."""
import copy
import json
import os
from pathlib import Path
import sqlite3
from codex_workspace.domain import domain
from codex_workspace.relay import migrations


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / 'workspace.sqlite3'
        db = self.connect()
        try:
            db.execute('PRAGMA journal_mode=WAL')
            migrations.migrate(db)
        finally:
            db.close()
        os.chmod(self.path,0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def mutate(self, operation):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            state = migrations.read_state(db)
            previous = copy.deepcopy(state)
            output = operation(state)
            value = json.dumps(state,ensure_ascii=False)
            if len(value.encode()) > 3000000:
                raise domain.Rejected('Mailbox capacity')
            migrations.write_state(db, state, previous)
            db.commit()
            return output
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
