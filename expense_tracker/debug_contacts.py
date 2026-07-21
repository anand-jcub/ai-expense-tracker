import json, pathlib

TRANSCRIPT = r'C:\Users\User\.gemini\antigravity\brain\1e3036f6-c81a-429a-a7ab-a61f2202c93c\.system_generated\logs\transcript.jsonl'

lines = []
with open(TRANSCRIPT, 'r', encoding='utf-8') as f:
    for line in f:
        lines.append(json.loads(line))

for data in lines:
    if data.get('type') != 'PLANNER_RESPONSE': continue
    for tc in data.get('tool_calls', []):
        if tc.get('name') != 'write_to_file': continue
        args = tc.get('args', {})
        t = args.get('TargetFile', '')
        try: t = json.loads(t)
        except: pass
        if 'contacts.py' in str(t):
            raw = args.get('CodeContent', '')
            print(f'Raw length: {len(raw)}')
            print(f'Raw type: {type(raw)}')
            print(f'Contains real newlines: {chr(10) in raw}')
            print(f'Contains \\\\n: {"\\\\n" in raw}')
            print(f'First char: {repr(raw[0])}')
            print(f'Second char: {repr(raw[1])}')
            print(f'Last char: {repr(raw[-1])}')
