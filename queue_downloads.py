"""Download and verify queued immutable attachments before dispatch."""
import base64
import hashlib
import json
import os
import re
from runtime_support import BridgeError


def downloads(queue, api):
    for row in queue.db.execute("SELECT * FROM requests WHERE status='pending'").fetchall():
        item = json.loads(row['payload'])
        attachments=item.get('attachments',[])
        if not attachments or json.loads(row['files']):
            continue
        directory=queue.state/'attachments'/str(row['id'])
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        saved=[]
        for attachment in attachments:
            ident=attachment.get('id','')
            if not re.fullmatch('[a-f0-9]{32}',ident) or not 0<attachment['size']<=5*1024*1024:
                raise BridgeError('Invalid queued attachment')
            match=re.search(r'\.[A-Za-z0-9]{1,12}$',attachment['name'])
            path=directory/(ident+(match.group(0) if match else '.bin'))
            temporary=path.with_suffix(path.suffix+'.part')
            count,index,digest=0,0,hashlib.sha256()
            fd=os.open(temporary,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
            try:
                with os.fdopen(fd,'wb') as output:
                    while count<attachment['size']:
                        chunk=api.call('/v2/files/get',{'id':ident,'index':index})
                        data=base64.b64decode(chunk['data'],validate=True)
                        if not data or len(data)>48*1024 or count+len(data)>attachment['size']:
                            raise BridgeError('Invalid attachment bytes')
                        output.write(data);digest.update(data);count+=len(data);index+=1
                if digest.hexdigest()!=attachment['sha256']:
                    raise BridgeError('Attachment checksum mismatch')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            saved.append({**attachment,'path':str(path.resolve())})
        with queue.db:
            queue.db.execute('UPDATE requests SET files=? WHERE id=?',(json.dumps(saved),row['id']))
