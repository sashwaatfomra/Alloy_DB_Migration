import gspread
from dotenv import load_dotenv
import os

load_dotenv()

gc = gspread.service_account(
    filename=os.getenv("GOOGLE_CREDENTIALS_FILE", "service-account.json")
)

spreadsheet = gc.open_by_key(os.getenv("SPREADSHEET_ID"))
worksheet = spreadsheet.worksheet(
    os.getenv("WORKSHEET_NAME", "Employee Database")
)

rows = worksheet.get_all_records()

print(f"Total rows: {len(rows)}")
print("\nStatus values longer than 30 characters:\n")

for row_number, row in enumerate(rows, start=2):
    status = str(row.get("Status", "")).strip()

    if len(status) > 30:
        print(
            f"Row {row_number} | "
            f"Employee: {row.get('Employee Code')} | "
            f"Name: {row.get('Full name')} | "
            f"Status length: {len(status)} | "
            f"Status: {status}"
        )