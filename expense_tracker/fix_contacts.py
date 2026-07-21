import json

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
            # The raw is a JSON string with real control chars (invalid strict JSON)
            # Use strict=False
            decoded = json.loads(raw, strict=False)
            print('Decoded length:', len(decoded))
            print('Decoded line count:', decoded.count('\n'))
            print('First 3 lines:', decoded.splitlines()[:3])
            
            with open('expense_tracker/contacts.py', 'w', encoding='utf-8') as out:
                out.write(decoded)
            print('Written contacts.py successfully!')
