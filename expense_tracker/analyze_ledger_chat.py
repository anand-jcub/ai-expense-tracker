import json
import sys

TRANSCRIPT = r'C:\Users\User\.gemini\antigravity\brain\1e3036f6-c81a-429a-a7ab-a61f2202c93c\.system_generated\logs\transcript.jsonl'

lines = []
with open(TRANSCRIPT, 'r', encoding='utf-8') as f:
    for line in f:
        lines.append(json.loads(line))

print(f"Total steps: {len(lines)}")
print()

# Print step summaries for steps 383+
for i in range(383, len(lines)):
    data = lines[i]
    t = data.get('type', '')
    si = data.get('step_index', i)
    if t == 'USER_INPUT':
        msg = data.get('content', '')[:150]
        print(f"STEP {si} USER: {msg}")
    elif t == 'PLANNER_RESPONSE':
        msg = data.get('content', '')[:100]
        if msg:
            print(f"STEP {si} AGENT: {msg}")
        if data.get('tool_calls'):
            for tc in data['tool_calls']:
                name = tc.get('name', '')
                args = tc.get('args', {})
                target = args.get('TargetFile', args.get('CommandLine', ''))
                try:
                    target = json.loads(target)
                except:
                    pass
                desc = args.get('Description', args.get('Instruction', ''))
                try:
                    desc = json.loads(desc)
                except:
                    pass
                print(f"  TOOL: {name} | {str(target)[-50:]} | {str(desc)[:60]}")
