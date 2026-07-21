import json

TRANSCRIPT = r'C:\Users\User\.gemini\antigravity\brain\10edf711-f316-4079-979c-bb1a873aa717\.system_generated\logs\transcript.jsonl'
lines = []
with open(TRANSCRIPT, 'r', encoding='utf-8') as f:
    for line in f:
        lines.append(json.loads(line))

out = open('main_chat_history.txt', 'w', encoding='utf-8')

for data in lines:
    t = data.get('type', '')
    si = data.get('step_index', '?')
    if t == 'USER_INPUT':
        content = data.get('content', '')
        if '<USER_REQUEST>' in content:
            start = content.find('<USER_REQUEST>') + 14
            end = content.find('</USER_REQUEST>')
            msg = content[start:end].strip()
            out.write(f'USER step {si}: {msg[:200]}\n\n')
    elif t == 'PLANNER_RESPONSE' and data.get('tool_calls'):
        for tc in data['tool_calls']:
            name = tc.get('name', '')
            args = tc.get('args', {})
            if name in ('replace_file_content', 'multi_replace_file_content', 'write_to_file'):
                t2 = args.get('TargetFile', '')
                try: t2 = json.loads(t2)
                except: pass
                d2 = args.get('Description', args.get('Instruction', ''))
                try: d2 = json.loads(d2)
                except: pass
                fname = str(t2).split('\\')[-1]
                out.write(f'  CODE step {si}: {name} | {fname} | {str(d2)[:120]}\n')
    elif t == 'PLANNER_RESPONSE' and data.get('content'):
        content = data['content']
        if len(content) > 100:
            out.write(f'AGENT step {si}: {content[:400]}\n\n')

out.close()
print('Written to main_chat_history.txt')
