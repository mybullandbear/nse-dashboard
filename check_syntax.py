"""Portable syntax validation for project Python sources.

Run from any working directory: python check_syntax.py
Does not import application modules or access broker credentials.
"""
from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parent
SKIP = {'.git', '.venv', 'venv', '__pycache__', 'node_modules'}
files = sorted(p for p in ROOT.rglob('*.py') if not any(x in SKIP for x in p.relative_to(ROOT).parts))
failures = []
for path in files:
    try:
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    except (SyntaxError, UnicodeError) as exc:
        failures.append((path.relative_to(ROOT), str(exc)))
print(f'Checked {len(files)} Python files')
if failures:
    for path, error in failures:
        print(f'FAIL {path}: {error}')
    sys.exit(1)
print('PASS: all Python files parse successfully')
