"""Read-only lexical dependency inventory, never proof of live elimination.

Only tracked text is read. Reports paths/line numbers/categories, never source
lines, values or credentials. Historical SQL/docs remain separate from runtime.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

PATTERNS = {
    'supabase': re.compile(r'supabase', re.I),
    'postgres_driver': re.compile(r'\b(?:asyncpg|psycopg\w*|postgresql)\b', re.I),
    'postgres_session_or_rls': re.compile(r'\b(?:row level security|set_config|current_setting)\b|SET LOCAL|FOR UPDATE', re.I),
    'database_access': re.compile(r'\b(?:user_connection|platform_connection|create_pool)\b'),
}

def scope(path):
    p=Path(path)
    if p.parts[0] in {'docs','migrations','database'} or p.suffix == '.md':
        return 'historical_or_schema'
    if p.parts[0] == 'tests':
        return 'tests'
    if p.parts[0] in {'tools','.github'} or p.parts[:2] == ('backend','scripts'):
        return 'migration_or_operations'
    return 'runtime_or_configuration'

def inventory(root, paths):
    findings=[]
    skipped=[]
    root=root.resolve()
    for name in sorted(set(paths)):
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            skipped.append(name)
            continue
        try:
            content=path.read_text(encoding='utf-8')
        except (UnicodeError, OSError):
            skipped.append(name)
            continue
        for category,pattern in PATTERNS.items():
            lines=[i for i,line in enumerate(content.splitlines(),1) if pattern.search(line)]
            if lines:
                findings.append({'path':name,'category':category,'scope':scope(name),'lines':lines})
    return {
        'status':'LEXICAL_INVENTORY_REQUIRES_RUNTIME_REVIEW',
        'count_unit':'unique tracked file and dependency category pair',
        'dependency_candidates':len(findings),
        'files_with_candidates':len({f['path'] for f in findings}),
        'by_scope':dict(sorted(Counter(f['scope'] for f in findings).items())),
        'findings':findings,'unread_files':skipped,
        'live_dependency_total':None,'dependencies_proven_eliminated':None,
        'production_cutover_authorized':False,
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'))
    args=parser.parse_args()
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=args.root).decode().split('\0')
    print(json.dumps(inventory(args.root,[p for p in paths if p]),indent=2))

if __name__=='__main__':
    main()
