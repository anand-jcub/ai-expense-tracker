import pypdf
from pathlib import Path

pdf_path = "C:/Users/User/Documents/SHA/DepositAccountStatementjul20.pdf"

phone_suffixes = ["66770", "77992", "37475", "79564", "60612"]
# Let's try years 1950 to 2010
years = list(range(50, 100)) + list(range(0, 15))

found_pw = None
reader = pypdf.PdfReader(pdf_path)

print("Starting brute force...", flush=True)
for suffix in phone_suffixes:
    if found_pw:
        break
    for y in years:
        if found_pw:
            break
        y_str = f"{y:02d}"
        for m in range(1, 13):
            if found_pw:
                break
            m_str = f"{m:02d}"
            for d in range(1, 32):
                dob = f"{d:02d}{m_str}{y_str}"
                pw = f"{suffix}{dob}"
                try:
                    if reader.decrypt(pw) > 0:
                        print(f"SUCCESS! Password is: {pw}", flush=True)
                        found_pw = pw
                        break
                except Exception:
                    continue

if not found_pw:
    print("Brute force failed.", flush=True)
