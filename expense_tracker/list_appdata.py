import os
from pathlib import Path

appdata = Path(r"C:\Users\User\.gemini\antigravity\brain\10edf711-f316-4079-979c-bb1a873aa717")

print(f"Listing directory: {appdata}")
for root, dirs, files in os.walk(appdata):
    for f in files:
        full_path = Path(root) / f
        try:
            rel = full_path.relative_to(appdata)
            print(rel)
        except Exception:
            print(full_path)
