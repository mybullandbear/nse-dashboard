"""Record the installed production dependency graph for a reproducible audited build."""
import importlib.metadata as metadata
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
seen={}
def visit(name,extras=frozenset()):
    name=canonicalize_name(name)
    if name in seen:return
    dist=metadata.distribution(name);seen[name]=dist.version
    for value in dist.requires or []:
        req=Requirement(value)
        if not req.marker or any(req.marker.evaluate({'extra':extra}) for extra in extras|{''}):
            visit(req.name,req.extras)
for line in Path('backend/requirements.txt').read_text().splitlines():
    if line.strip() and not line.startswith('#'):
        req=Requirement(line.strip());visit(req.name,req.extras)
Path('backend/requirements.lock').write_text('# Python 3.12 production lock; regenerate only after review and audit.\n'+''.join(f'{key}=={value}\n' for key,value in sorted(seen.items())))
