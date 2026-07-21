"""
Full replay script: applies all edits from the ledger chat transcript to the current codebase.
Processes in chronological order, up to step 383 (confirmed working state).
"""
import json
import pathlib
import sys
import shutil

TRANSCRIPT = r'C:\Users\User\.gemini\antigravity\brain\1e3036f6-c81a-429a-a7ab-a61f2202c93c\.system_generated\logs\transcript.jsonl'
BASE_DIR = pathlib.Path(r'C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai')
EXPENSE_DIR = BASE_DIR / 'expense_tracker'

SKIP_FILES = {
    'inspect_db.py', 'check_db.py', 'check_db2.py', 
    'analyze_ledger_chat.py', 'replay_edits.py',
    'extract_new_files.py', 'full_replay.py'
}
KEY_FILES = {'db.py', 'services.py', 'templates.py', 'web.py', 'app.js', 'contacts.py', 'connections.py'}

lines = []
with open(TRANSCRIPT, 'r', encoding='utf-8') as f:
    for line in f:
        lines.append(json.loads(line))

print(f"Total steps: {len(lines)}", flush=True)

def resolve_target(target_raw):
    try:
        target = json.loads(target_raw)
    except:
        target = target_raw
    return pathlib.Path(str(target))

def get_content(raw):
    try:
        return json.loads(raw)
    except:
        return raw

def apply_replace(filepath, start_line, end_line, target_content, replacement_content, allow_multiple=False):
    """Apply a replace_file_content patch."""
    if not filepath.exists():
        print(f"  ERROR: file not found: {filepath}")
        return False
    
    text = filepath.read_text(encoding='utf-8')
    lines_list = text.splitlines(keepends=True)
    
    # Search for target within line range
    chunk = ''.join(lines_list[start_line-1:end_line])
    
    if target_content not in chunk:
        # Try broader search
        if target_content in text:
            print(f"  WARNING: target found outside line range {start_line}-{end_line}, doing full replace")
            if text.count(target_content) > 1 and not allow_multiple:
                print(f"  ERROR: multiple occurrences found, skipping")
                return False
            new_text = text.replace(target_content, replacement_content, 1)
            filepath.write_text(new_text, encoding='utf-8')
            return True
        else:
            print(f"  ERROR: target content not found in file")
            print(f"  Target (first 100): {repr(target_content[:100])}")
            return False
    
    new_chunk = chunk.replace(target_content, replacement_content, 1)
    new_lines = lines_list[:start_line-1] + [new_chunk] + lines_list[end_line:]
    filepath.write_text(''.join(new_lines), encoding='utf-8')
    return True

applied = 0
skipped = 0
errors = 0

for i, data in enumerate(lines):
    if i > 395:  # stop after the last db.py cleanup fix (step 383+)
        break
    if data.get('type') != 'PLANNER_RESPONSE':
        continue
    if not data.get('tool_calls'):
        continue
    
    si = data.get('step_index', i)
    
    for tc in data['tool_calls']:
        name = tc.get('name')
        if name not in ('replace_file_content', 'multi_replace_file_content', 'write_to_file'):
            continue
        
        args = tc.get('args', {})
        target_raw = args.get('TargetFile', '')
        if not target_raw:
            continue
        
        target_path = resolve_target(target_raw)
        fname = target_path.name
        
        # Skip debug/scratch files
        if fname in SKIP_FILES:
            continue
        
        # Only process files we care about
        if fname not in KEY_FILES:
            # But allow write_to_file for new modules
            if name != 'write_to_file':
                continue
            if 'expense_tracker' not in str(target_path):
                continue
        
        # Handle write_to_file
        if name == 'write_to_file':
            content_raw = args.get('CodeContent', '')
            content = get_content(content_raw)
            
            # Normalize path to BASE_DIR
            # Target might have full absolute path
            target_str = str(target_path)
            if 'expense_tracker' in target_str:
                # Find expense_tracker part
                idx = target_str.find('expense_tracker')
                rel = target_str[idx:]
                dest = BASE_DIR / rel
            else:
                dest = BASE_DIR / target_path.name
            
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding='utf-8')
            print(f"[step {si}] WROTE: {dest.name} ({len(content)} chars)")
            applied += 1
            continue
        
        # Normalize file path
        target_str = str(target_path)
        if 'expense_tracker' in target_str:
            idx = target_str.find('expense_tracker')
            rel = target_str[idx:]
            filepath = BASE_DIR / rel
        elif fname in KEY_FILES:
            filepath = EXPENSE_DIR / fname
        else:
            continue
        
        if name == 'replace_file_content':
            start = int(args.get('StartLine', 1))
            end = int(args.get('EndLine', start))
            target_content_raw = args.get('TargetContent', '')
            replacement_raw = args.get('ReplacementContent', '')
            allow_multiple = bool(args.get('AllowMultiple', False))
            
            target_content = get_content(target_content_raw)
            replacement = get_content(replacement_raw)
            
            desc_raw = args.get('Description', args.get('Instruction', ''))
            try: desc = json.loads(desc_raw)
            except: desc = desc_raw
            
            print(f"[step {si}] PATCH {fname} lines {start}-{end}: {str(desc)[:60]}")
            
            ok = apply_replace(filepath, start, end, target_content, replacement, allow_multiple)
            if ok:
                applied += 1
            else:
                errors += 1
        
        elif name == 'multi_replace_file_content':
            chunks_raw = args.get('ReplacementChunks', '[]')
            try:
                chunks = json.loads(chunks_raw)
            except:
                chunks = []
            
            desc_raw = args.get('Description', args.get('Instruction', ''))
            try: desc = json.loads(desc_raw)
            except: desc = desc_raw
            
            print(f"[step {si}] MULTI-PATCH {fname} ({len(chunks)} chunks): {str(desc)[:60]}")
            
            chunk_ok = 0
            chunk_err = 0
            for chunk in chunks:
                start = int(chunk.get('StartLine', 1))
                end = int(chunk.get('EndLine', start))
                target_c = get_content(chunk.get('TargetContent', ''))
                replacement_c = get_content(chunk.get('ReplacementContent', ''))
                allow_m = bool(chunk.get('AllowMultiple', False))
                ok = apply_replace(filepath, start, end, target_c, replacement_c, allow_m)
                if ok: chunk_ok += 1
                else: chunk_err += 1
            
            if chunk_err == 0:
                applied += 1
            else:
                errors += 1
            print(f"  -> {chunk_ok} ok, {chunk_err} errors")

print(f"\nDone! Applied: {applied}, Skipped: {skipped}, Errors: {errors}")
