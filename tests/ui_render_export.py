"""Optional isolated-test render snapshots for browser QA; never live records."""
import os
from pathlib import Path

def export(response,name):
    destination=os.environ.get('NEXORA_UX_RENDER')
    if destination:
        assert response.status_code==200, response.status_code
        folder=Path(destination);folder.mkdir(parents=True,exist_ok=True)
        (folder/(name+'.html')).write_text(response.content.decode().replace('"/static/','"http://127.0.0.1:8768/static/'),encoding='utf-8')
