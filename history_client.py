#!/usr/bin/env python3
"""Publish public messages returned by the authorized Codex read_thread tool."""
import argparse
import json
import re
import os
from pathlib import Path
from bridge import BridgeError, exclusive
from cloud_client import API, STATE


def public_text(text):
    # Do not export recognizable credentials even if pasted in a visible message.
    text=re.sub(r'\b\d{6,15}:[A-Za-z0-9_-]{30,}\b','[Telegram token hidden]',text)
    text=re.sub(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b','[credential hidden]',text)
    return re.sub(r'(?im)^(\s*(?:export\s+)?[A-Z_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z_]*\s*=).+$',r'\1[hidden]',text)


def messages(read):
    result=[]
    for turn in read.get('turns',[]):
        items=turn.get('items',[])
        created=turn.get('startedAt')
        if not isinstance(created,(int,float)) or created<0:continue
        for index,item in enumerate(items):
            if item.get('type')=='userMessage':
                text='\n'.join(part.get('text','') for part in item.get('content',[]) if part.get('type')=='text')
                role='user'
            elif item.get('type')=='agentMessage' and item.get('phase') in ('commentary','final_answer'):
                text=item.get('text','');role='assistant'
            else:continue
            if not isinstance(text,str) or not text.strip():continue
            if role=='user' and text.startswith(('Workspace request: ','Транспортная квитанция для ')):continue
            created=item.get('createdAt',turn.get('startedAt'))
            if not isinstance(created,(int,float)) or created<0:continue
            text=public_text(text)
            ident=str(item.get('id') or f"{turn['id']}:{index}")
            # Split very long visible messages, preserving all text and ordering.
            for part,start in enumerate(range(0,len(text),6000)):
                position=item.get('position') or f"{int(created*1000):016d}:{turn['id']}:{index:06d}"
                result.append({'id':f'{ident}:{part}', 'position':f'{position}:{part:04d}',
                               'turn_id':turn['id'],'phase':item.get('phase') if part==0 else None,'created':int(created),'role':role,'text':text[start:start+6000]})
    return result


def publish(api,read,mode):
    thread=read.get('thread',{}).get('id')
    if not isinstance(thread,str) or not isinstance(read.get('turns'),list):raise BridgeError('Invalid thread tool response')
    batch=[];count=0
    for item in messages(read):
        if batch and (len(batch)>=100 or len(json.dumps(batch+[item]).encode())>80000):
            api.call('/v2/history/publish',{'thread':thread,'messages':batch});count+=len(batch);batch=[]
        batch.append(item)
    if batch:api.call('/v2/history/publish',{'thread':thread,'messages':batch});count+=len(batch)
    page=read.get('page',{})
    api.call('/v2/history/publish',{'thread':thread,'messages':[],'finish':True,'mode':mode,
        'cursor':page.get('nextCursor'),'more':bool(page.get('hasMore'))})
    return {'count':count,'empty_turns':sum(not t.get('items') for t in read['turns']),'more':bool(page.get('hasMore'))}


def sync_catalog(api, catalog, project, root):
    # Import lazily: history_sync uses this module's public-message adapter.
    from history_sync import sync_once
    failures = {}
    count = sync_once(api, catalog, project, root, {}, failures)
    return {'messages': count, 'failed_tasks': len(failures)}


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('pending');command=sub.add_parser('publish');command.add_argument('file',type=Path);command.add_argument('--mode',choices=['latest','older'],required=True)
    sync=sub.add_parser('sync');sync.add_argument('--catalog',type=Path,required=True)
    args=parser.parse_args()
    try:
        config=json.loads((STATE/'web.json').read_text())
        if config.get('paused',True):print('{"status":"paused"}');return
        with exclusive(STATE):
            api=API(config)
            if args.command=='sync':
                catalog=json.loads(args.catalog.read_text())
                root=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'sessions'
                result=sync_catalog(api,catalog,config['project_id'],root)
            else:
                result=api.call('/v2/history/pending',{}) if args.command=='pending' else publish(api,json.loads(args.file.read_text()),args.mode)
        print(json.dumps(result,ensure_ascii=False))
        if result.get('failed_tasks'):
            raise SystemExit(1)
    except (BridgeError,OSError,ValueError,KeyError):
        raise SystemExit('History sync failed; content and credentials hidden')


if __name__=='__main__':main()
