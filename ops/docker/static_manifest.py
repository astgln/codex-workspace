"""Build an allowlist for the relay's static file server."""
import json
import mimetypes
from pathlib import Path
import sys
root=Path(sys.argv[1])
manifest={}
for path in sorted(root.rglob('*')):
    if path.is_file():
        name=path.relative_to(root).as_posix()
        manifest['/' if name=='index.html' else '/'+name]={'file':name,'type':mimetypes.guess_type(name)[0] or 'application/octet-stream'}
(root/'files.json').write_text(json.dumps(manifest))
