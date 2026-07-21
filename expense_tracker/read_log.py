from pathlib import Path

src = Path(r"C:\Users\User\.gemini\antigravity\brain\10edf711-f316-4079-979c-bb1a873aa717\.system_generated\tasks\task-2266.log")
dst = Path(r"c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\task_log.txt")

if src.exists():
    dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    print("Log copied successfully.")
else:
    print("Log file does not exist yet.")
