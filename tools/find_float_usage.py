import os
import re
import json

root = '.'
patterns = [re.compile(r'\bfloat\('), re.compile(r'\b0\b')]
results = {}

for dirpath, dirs, files in os.walk(root):
    if any(p in dirpath for p in ['.venv', '.git', 'node_modules']):
        continue
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(dirpath, f)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                s = fh.read()
                hits = []
                for m in re.finditer(r'\bfloat\(', s):
                    line = s.count('\n', 0, m.start()) + 1
                    hits.append({'type': 'float_call', 'line': line})
                if hits:
                    results[path] = hits
        except Exception:
            pass

print(json.dumps(results, indent=2))
