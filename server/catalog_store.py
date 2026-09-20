"""Typed catalog rows; preserve optional fields and unknown extensions losslessly."""
import json

ENTITIES = {
    'projects': ('catalog_projects', ('id', 'title')),
    'catalog': ('catalog_tasks', ('id', 'project_id', 'title', 'status', 'read_only')),
}


def create(db):
    db.execute('CREATE TABLE catalog_sections(name TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE catalog_projects(key TEXT PRIMARY KEY,position INTEGER NOT NULL,id TEXT,title TEXT,fields INTEGER NOT NULL,extensions TEXT NOT NULL)')
    db.execute('CREATE TABLE catalog_tasks(key TEXT PRIMARY KEY,position INTEGER NOT NULL,id TEXT,project_id TEXT,title TEXT,status TEXT,read_only INTEGER CHECK(read_only IN (0,1)),fields INTEGER NOT NULL,extensions TEXT NOT NULL)')
    db.execute('CREATE INDEX catalog_tasks_project ON catalog_tasks(project_id)')


def read(db, state):
    for section, in db.execute('SELECT name FROM catalog_sections'):
        state[section] = {}
    for section, (table, columns) in ENTITIES.items():
        for row in db.execute('SELECT key,' + ','.join(columns) + ',fields,extensions FROM ' + table + ' ORDER BY position'):
            key, values, mask, extra = row[0], row[1:-2], row[-2], json.loads(row[-1])
            for index, (column, value) in enumerate(zip(columns, values)):
                if mask & (1 << index):
                    extra[column] = bool(value) if column == 'read_only' and value is not None else value
            state[section][key] = extra


def write(db, state):
    db.execute('DELETE FROM catalog_sections')
    for section, (table, columns) in ENTITIES.items():
        db.execute('DELETE FROM ' + table)
        if section not in state:
            continue
        db.execute('INSERT INTO catalog_sections VALUES(?)', (section,))
        for position, (key, item) in enumerate(state[section].items()):
            mask = sum(1 << i for i, column in enumerate(columns) if column in item)
            extra = {k: v for k, v in item.items() if k not in columns}
            values = [item.get(column) for column in columns]
            db.execute('INSERT INTO ' + table + ' VALUES(' + ','.join('?' for _ in range(len(columns) + 4)) + ')',
                       [key, position, *values, mask, json.dumps(extra, ensure_ascii=False)])


def drop(db):
    for table in ('catalog_tasks', 'catalog_projects', 'catalog_sections'):
        db.execute('DROP TABLE ' + table)
