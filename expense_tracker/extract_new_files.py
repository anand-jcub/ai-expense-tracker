"""
Extracts ALL new files written in the ledger chat and saves them.
"""
import json
import pathlib
import sys

TRANSCRIPT = r'C:\Users\User\.gemini\antigravity\brain\1e3036f6-c81a-429a-a7ab-a61f2202c93c\.system_generated\logs\transcript.jsonl'
BASE_DIR = pathlib.Path(r'C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai')

lines = []
with open(TRANSCRIPT, 'r', encoding='utf-8') as f:
    for line in f:
        lines.append(json.loads(line))

print(f"Total steps: {len(lines)}", flush=True)

# Find all write_to_file calls for expense_tracker files (not scratch/debug)
for data in lines:
    if data.get('type') != 'PLANNER_RESPONSE':
        continue
    for tc in data.get('tool_calls', []):
        name = tc.get('name')
        if name != 'write_to_file':
            continue
        args = tc.get('args', {})
        target_raw = args.get('TargetFile', '')
        try:
            target = json.loads(target_raw)
        except:
            target = target_raw
        if not target or 'expense_tracker' not in str(target):
            continue
        # Skip scratch files
        fname = pathlib.Path(target).name
        if fname in ('inspect_db.py', 'check_db.py', 'check_db2.py', 'analyze_ledger_chat.py', 'replay_edits.py'):
            continue
        
        content_raw = args.get('CodeContent', '')
        try:
            content = json.loads(content_raw)
        except:
            content = content_raw
        
        dest = BASE_DIR / pathlib.Path(target).relative_to(pathlib.Path(target).anchor)
        print(f"WRITE: {dest.name} ({len(content)} chars)")
        
        # Write the file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding='utf-8')
        print(f"  -> Written to {dest}")

print("Done!", flush=True)
