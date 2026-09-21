"""Validated project/task catalog snapshots and target revocation."""
import re
from . import domain
from .access import Forbidden


def sync_catalog(state, body, project, now):
    if body.get('project_id') != project:
        raise Forbidden()
    project_entries = body.get('projects', [{'id':project,'title':'Project'}])
    if not isinstance(project_entries,list) or len(project_entries)>100:
        raise domain.Rejected('Invalid projects')
    projects={}
    for entry in project_entries:
        if (not isinstance(entry,dict) or not isinstance(entry.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',entry['id'])
                or not isinstance(entry.get('title'),str) or not 1<=len(entry['title'])<=200 or entry['id'] in projects):
            raise domain.Rejected('Invalid project')
        projects[entry['id']]={'id':entry['id'],'title':entry['title']}
    entries = body.get('threads')
    if not isinstance(entries, list) or len(entries) > 1000:
        raise domain.Rejected('Invalid catalog')
    catalog = {}
    for entry in entries:
        if (not isinstance(entry, dict) or not re.fullmatch(r'[a-zA-Z0-9-]{10,80}', str(entry.get('id', '')))
                or entry.get('project_id') not in projects or not isinstance(entry.get('title'), str)
                or not 1 <= len(entry['title']) <= 200):
            raise domain.Rejected('Invalid thread')
        if entry['id'] in catalog:
            raise domain.Rejected('Duplicate thread')
        catalog[entry['id']] = {'id': entry['id'], 'title': entry['title'], 'project_id':entry['project_id'],
            'status': entry.get('status') if entry.get('status') in ('active', 'idle', 'notLoaded') else 'unknown',
            'read_only': entry.get('read_only') is True}
    state['projects'] = projects
    state['catalog'] = catalog
    state['catalog_updated'] = now
    # Revoking a target immediately stops every not-yet-delivered request to it.
    for item in state['items'].values():
        if item.get('channel') == 'web' and (item['thread'] not in catalog or catalog[item['thread']].get('read_only')) and item['status'] == 'queued':
            item['status'] = 'target_unavailable'
    return {'count': len(catalog)}
