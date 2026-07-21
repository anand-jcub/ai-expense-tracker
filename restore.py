import json
import os

transcript_path = r'C:\Users\User\.gemini\antigravity\brain\1e3036f6-c81a-429a-a7ab-a61f2202c93c\.system_generated\logs\transcript.jsonl'
codebase_path = r'C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\expense_tracker'

def load_transcript():
    events = []
    with open(transcript_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            events.append(json.loads(line))
    return events

events = load_transcript()

file_contents = {}

def get_file_content(path):
    if path in file_contents:
        return file_contents[path]
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = ""
    file_contents[path] = content
    return content

def set_file_content(path, content):
    file_contents[path] = content
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

# We want up to step 395
# Note: The transcript has a `step_index` field. Let's use that.
for event in events:
    step = event.get("step_index", 0)
    if step > 395:
        break
    
    if event.get("source") == "MODEL" and "tool_calls" in event:
        for call in event["tool_calls"]:
            name = call.get("name")
            if name in ["replace_file_content", "multi_replace_file_content", "write_to_file"]:
                args_dict = call.get("args", {})
                
                # The values in args_dict might be JSON strings or regular values. 
                # Let's decode them if they are JSON strings.
                parsed_args = {}
                for k, v in args_dict.items():
                    if isinstance(v, str):
                        try:
                            parsed_args[k] = json.loads(v)
                        except:
                            parsed_args[k] = v
                    else:
                        parsed_args[k] = v

                target_file = parsed_args.get("TargetFile")
                if not target_file:
                    continue
                
                basename = os.path.basename(target_file)
                if basename not in ["db.py", "web.py", "templates.py", "app.js", "services.py", "contacts.py"]:
                    continue

                if basename == "app.js":
                    local_path = os.path.join(codebase_path, "static", "app.js")
                else:
                    local_path = os.path.join(codebase_path, basename)
                    
                if name == "write_to_file":
                    content = parsed_args.get("CodeContent", "")
                    print(f"Step {step}: write_to_file {basename}")
                    set_file_content(local_path, content)
                
                elif name == "replace_file_content":
                    content = get_file_content(local_path)
                    target = parsed_args.get("TargetContent", "")
                    replacement = parsed_args.get("ReplacementContent", "")
                    if target in content:
                        print(f"Step {step}: replace_file_content {basename} SUCCESS")
                        content = content.replace(target, replacement, 1)
                        set_file_content(local_path, content)
                    else:
                        print(f"Step {step}: replace_file_content {basename} FAILED")
                
                elif name == "multi_replace_file_content":
                    content = get_file_content(local_path)
                    chunks = parsed_args.get("ReplacementChunks", [])
                    if isinstance(chunks, str):
                        try:
                            chunks = json.loads(chunks)
                        except:
                            chunks = []
                    
                    for chunk in chunks:
                        target = chunk.get("TargetContent", "")
                        replacement = chunk.get("ReplacementContent", "")
                        if target in content:
                            print(f"Step {step}: multi_replace_file_content {basename} chunk SUCCESS")
                            content = content.replace(target, replacement, 1)
                        else:
                            print(f"Step {step}: multi_replace_file_content {basename} chunk FAILED")
                    set_file_content(local_path, content)

print("Finished applying patches.")
