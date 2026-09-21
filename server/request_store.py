"""Relational requests, uploads, attachment snapshots and response events."""
import json

REQUEST_FIELDS = {
    'id':'INTEGER', 'source':'TEXT', 'channel':'TEXT', 'sender':'INTEGER',
    'message':'INTEGER', 'thread':'TEXT', 'text':'TEXT', 'snapshot':'TEXT',
    'created':'INTEGER', 'expires':'INTEGER', 'status':'TEXT',
    'lease':'TEXT', 'lease_until':'INTEGER',
    'delivered_at':'INTEGER', 'result_revision':'INTEGER', 'result_digest':'TEXT',
    'result_status':'TEXT', 'result_updated':'INTEGER',
}
UPLOAD_FIELDS = {
    'id':'TEXT', 'owner':'INTEGER', 'thread':'TEXT', 'name':'TEXT', 'size':'INTEGER',
    'sha256':'TEXT', 'created':'INTEGER', 'expires':'INTEGER', 'status':'TEXT',
    'request_id':'TEXT', 'used_by':'INTEGER',
}
ENTITIES = {'items': ('workspace_requests', REQUEST_FIELDS), 'uploads': ('workspace_uploads', UPLOAD_FIELDS)}


def create(db):
    db.execute('CREATE TABLE request_sections(name TEXT PRIMARY KEY)')
    for table, fields in ENTITIES.values():
        db.execute('CREATE TABLE ' + table + '(key TEXT PRIMARY KEY,position INTEGER NOT NULL,' +
                   ','.join(name+' '+kind for name,kind in fields.items()) +
                   ',fields INTEGER NOT NULL,extensions TEXT NOT NULL)')
    db.execute('CREATE INDEX requests_status ON workspace_requests(status,created)')
    db.execute('CREATE INDEX requests_thread ON workspace_requests(thread,created)')
    db.execute('CREATE INDEX uploads_owner_nonce ON workspace_uploads(owner,request_id)')
    db.execute('CREATE TABLE request_events(request_key TEXT NOT NULL,position INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(request_key,position),FOREIGN KEY(request_key) REFERENCES workspace_requests(key) ON DELETE CASCADE)')
    db.execute('CREATE TABLE request_attachments(request_key TEXT NOT NULL,position INTEGER NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,extensions TEXT NOT NULL,PRIMARY KEY(request_key,position),FOREIGN KEY(request_key) REFERENCES workspace_requests(key) ON DELETE CASCADE)')


def read(db, state, historical=False):
    for section, in db.execute('SELECT name FROM request_sections'):
        state[section] = {}
    for section, (table, fields) in ENTITIES.items():
        if historical:
            fields = [row[1] for row in db.execute('PRAGMA table_info('+table+')')][2:-2]
        for row in db.execute('SELECT key,' + ','.join(fields) + ',fields,extensions FROM '+table+' ORDER BY position'):
            key, values, mask, item = row[0], row[1:-2], row[-2], json.loads(row[-1])
            for index, (name, value) in enumerate(zip(fields, values)):
                if mask & (1 << index):
                    item[name] = value
            state[section][key] = item
    for key, value in db.execute('SELECT request_key,value FROM request_events ORDER BY position'):
        state['items'][key]['events'].append(json.loads(value))
    for key, ident, name, size, digest, extensions in db.execute('SELECT request_key,id,name,size,sha256,extensions FROM request_attachments ORDER BY position'):
        state['items'][key]['attachments'].append({**json.loads(extensions), 'id':ident,'name':name,'size':size,'sha256':digest})


def write(db, state):
    for table in ('request_events','request_attachments','workspace_requests','workspace_uploads','request_sections'):
        db.execute('DELETE FROM '+table)
    for section, (table, fields) in ENTITIES.items():
        if section not in state:
            continue
        db.execute('INSERT INTO request_sections VALUES(?)',(section,))
        for position, (key, item) in enumerate(state[section].items()):
            mask = sum(1 << index for index,name in enumerate(fields) if name in item)
            extra = {k:v for k,v in item.items() if k not in fields}
            if section == 'items':
                for child in ('events','attachments'):
                    if child in extra:
                        extra[child] = []
            db.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in range(len(fields)+4))+')',
                       [key, position, *(item.get(name) for name in fields), mask, json.dumps(extra,ensure_ascii=False)])
            if section == 'items':
                db.executemany('INSERT INTO request_events VALUES(?,?,?)',
                    [(key,i,json.dumps(event,ensure_ascii=False)) for i,event in enumerate(item.get('events',[]))])
                for index, attachment in enumerate(item.get('attachments',[])):
                    extension = {k:v for k,v in attachment.items() if k not in ('id','name','size','sha256')}
                    db.execute('INSERT INTO request_attachments VALUES(?,?,?,?,?,?,?)',
                        [key,index,*(attachment[k] for k in ('id','name','size','sha256')),json.dumps(extension,ensure_ascii=False)])


def drop(db):
    for table in ('request_events','request_attachments','workspace_requests','workspace_uploads','request_sections'):
        db.execute('DROP TABLE '+table)
