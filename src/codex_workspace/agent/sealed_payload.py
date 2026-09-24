"""Bounded encrypted fragments for large response event lists."""
import hashlib
import json
from codex_workspace.crypto.workspace_crypto import CryptoError, encode


def publish(channel,scope,record,revision,payload):
    raw=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    if len(raw)<=67984:return channel.publish(scope,'response',record,revision,payload)
    if len(raw)>4*1024*1024:raise CryptoError('Response exceeds encrypted assembly limit')
    parts=[]
    for start in range(0,len(raw),48*1024):
        chunk=raw[start:start+48*1024]
        digest=hashlib.sha256(chunk).hexdigest();ident='part:'+digest
        channel.publish(scope,'response',ident,1,{'data':encode(chunk)})
        parts.append(ident)
    return channel.publish(scope,'response',record,revision,
                           {'payload_type':'parts-v1','parts':parts,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
