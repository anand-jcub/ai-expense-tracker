"""
Replays all file edits from the ledger chat transcript onto the current codebase.
Only replays edits to key files: db.py, services.py, templates.py, web.py, app.js
"""
import json
import pathlib
import re

TRANSCRIPT = r'C:\Users\User\.gemini\antigravity\brain\1e3036f6-c81a-429a-a7ab-a61f2202c93c\.system_generated\logs\transcript.jsonl'
BASE_DIR = pathlib.Path(r'C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai')

KEY_FILES = ['db.py', 'services.py', 'templates.py', 'web.py', 'app.js']

lines = []
with open(TRANSCRIPT, 'r', encoding='utf-8') as f:
    for line in f:
        lines.append(json.loads(line))

print(f"Total steps: {len(lines)}")

# Collect all edits in order, up to step 383 (when it was confirmed working)
edits = []
for i, data in enumerate(lines):
    if i > 383:
        break  # stop at the confirmed-working state
    if data.get('type') != 'PLANNER_RESPONSE':
        continue
    if not data.get('tool_calls'):
        continue
    for tc in data['tool_calls']:
        name = tc.get('name')
        if name not in ('replace_file_content', 'multi_replace_file_content', 'write_to_file'):
            continue
        args = tc.get('args', {})
        target_raw = args.get('TargetFile', '')
        try:
            target = json.loads(target_raw)
        except:
            target = target_raw
        if not target:
            continue
        fname = pathlib.Path(target).name
        if fname not in KEY_FILES:
            continue
        edits.append((i, name, target, args, fname))

print(f"\nFound {len(edits)} edits to replay:")
for idx, (step, name, target, args, fname) in enumerate(edits):
    desc = args.get('Description', args.get('Instruction', ''))
    try: desc = json.loads(desc)
    except: pass
    print(f"  [{idx}] step={step} {name} | {fname} | {str(desc)[:70]}")
