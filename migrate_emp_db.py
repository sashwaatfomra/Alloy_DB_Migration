import os
from datetime import datetime

import gspread
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

GOOGLE_CREDENTIALS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    "service-account.json"
)

SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    "1lW9ahTEr2WHKZkfIvu5T5-Pmyckb5HT1FMdQHmfahX0"
)

WORKSHEET_NAME = os.getenv(
    "WORKSHEET_NAME",
    "Employee Database"
)


# ============================================================
# VALIDATE CONFIGURATION
# ============================================================

def validate_configuration():
    required = {
        "DB_HOST": DB_HOST,
        "DB_NAME": DB_NAME,
        "DB_USER": DB_USER,
        "DB_PASSWORD": DB_PASSWORD,
        "SPREADSHEET_ID": SPREADSHEET_ID,
        "GOOGLE_CREDENTIALS_FILE": GOOGLE_CREDENTIALS_FILE,
    }

    missing = [
        key
        for key, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing configuration values: "
            + ", ".join(missing)
        )

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Google service account file not found: "
            f"{GOOGLE_CREDENTIALS_FILE}"
        )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def read_google_sheet():
    print("\n[1/3] Connecting to Google Sheets...")

    gc = gspread.service_account(
        filename=GOOGLE_CREDENTIALS_FILE
    )

    spreadsheet = gc.open_by_key(
        SPREADSHEET_ID
    )

    worksheet = spreadsheet.worksheet(
        WORKSHEET_NAME
    )

    rows = worksheet.get_all_records()

    print("Google Sheet connected successfully.")
    print(f"Rows found: {len(rows)}")

    if not rows:
        raise RuntimeError(
            "No employee records were found in the Google Sheet."
        )

    print("\nSheet columns:")
    print(list(rows[0].keys()))

    return rows


# ============================================================
# DATA CLEANING
# ============================================================

def clean_value(value):
    """
    Convert empty values to None.
    Trim whitespace from strings.
    """

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if value == "":
            return None

    return value


def parse_date(value):
    """
    Convert Google Sheet date values into Python date objects.

    Supported formats:
        DD/MM/YYYY
        YYYY-MM-DD
        MM/DD/YYYY
    """

    value = clean_value(value)

    if value is None:
        return None

    if hasattr(value, "date"):
        return value.date()

    date_formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]

    for date_format in date_formats:
        try:
            return datetime.strptime(
                str(value),
                date_format
            ).date()
        except ValueError:
            continue

    raise ValueError(
        f"Unable to parse date value: {value}"
    )


# ============================================================
# TRANSFORM SHEET ROW
# ============================================================

def transform_employee(row):
    """
    Convert one Google Sheet row into
    the public.emp_db structure.
    """

    techo_id = clean_value(
        row.get("Employee Code")
    )

    if not techo_id:
        raise ValueError(
            "Employee Code is missing."
        )

    return {
        "techo_id": techo_id,

        "full_name": clean_value(
            row.get("Full name")
        ),

        "work_email": clean_value(
            row.get("Work email")
        ),

        "department": clean_value(
            row.get("Department")
        ),

        "designation": clean_value(
            row.get("Designation")
        ),

        "reporting_manager": clean_value(
            row.get("Reporting manager")
        ),

        "date_of_joining": parse_date(
            row.get("Date of joining")
        ),

        "status": clean_value(
            row.get("Status")
        ),

        # The current Employee Database sheet
        # does not contain belt_id.
        "belt_id": None,
    }


# ============================================================
# ALLOYDB CONNECTION
# ============================================================

def connect_to_alloydb():
    print("\n[2/3] Connecting to AlloyDB...")

    connection = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode="require",
        connect_timeout=15,
    )

    print("AlloyDB connected successfully.")

    return connection


# ============================================================
# BATCH UPSERT
# ============================================================

def migrate_employees(cursor, employees):
    """
    Insert all employees in one batch.

    If techo_id already exists, update the existing
    employee record instead of creating a duplicate.
    """

    query = """
        INSERT INTO public.emp_db (
            techo_id,
            full_name,
            work_email,
            department,
            designation,
            reporting_manager,
            date_of_joining,
            status,
            belt_id
        )
        VALUES %s

        ON CONFLICT (techo_id)
        DO UPDATE SET
            full_name = EXCLUDED.full_name,
            work_email = EXCLUDED.work_email,
            department = EXCLUDED.department,
            designation = EXCLUDED.designation,
            reporting_manager = EXCLUDED.reporting_manager,
            date_of_joining = EXCLUDED.date_of_joining,
            status = EXCLUDED.status,
            belt_id = EXCLUDED.belt_id,
            updated_at = CURRENT_TIMESTAMP;
    """

    values = [
        (
            employee["techo_id"],
            employee["full_name"],
            employee["work_email"],
            employee["department"],
            employee["designation"],
            employee["reporting_manager"],
            employee["date_of_joining"],
            employee["status"],
            employee["belt_id"],
        )
        for employee in employees
    ]

    execute_values(
        cursor,
        query,
        values,
        page_size=100
    )


# ============================================================
# MAIN MIGRATION
# ============================================================

def main():

    print("=" * 60)
    print("EMPLOYEE DATABASE MIGRATION")
    print("Google Sheets -> AlloyDB")
    print("=" * 60)

    # --------------------------------------------------------
    # Validate configuration
    # --------------------------------------------------------

    validate_configuration()

    # --------------------------------------------------------
    # Read Google Sheet
    # --------------------------------------------------------

    rows = read_google_sheet()

    # --------------------------------------------------------
    # Transform data
    # --------------------------------------------------------

    print("\nPreparing employee records...")

    employees = []
    failed_rows = []

    for row_number, row in enumerate(
        rows,
        start=2
    ):
        try:
            employee = transform_employee(row)
            employees.append(employee)

        except Exception as error:
            failed_rows.append(
                {
                    "row": row_number,
                    "error": str(error),
                }
            )

    print(
        f"Valid employee records: {len(employees)}"
    )

    print(
        f"Invalid employee records: "
        f"{len(failed_rows)}"
    )

    # --------------------------------------------------------
    # Stop if no valid records
    # --------------------------------------------------------

    if not employees:
        raise RuntimeError(
            "No valid employee records available for migration."
        )

    # --------------------------------------------------------
    # Show validation errors
    # --------------------------------------------------------

    if failed_rows:

        print("\nRows skipped during validation:")

        for item in failed_rows:
            print(
                f"Row {item['row']}: "
                f"{item['error']}"
            )

    # --------------------------------------------------------
    # Connect to AlloyDB
    # --------------------------------------------------------

    connection = connect_to_alloydb()

    cursor = connection.cursor()

    try:

        # ----------------------------------------------------
        # Perform migration
        # ----------------------------------------------------

        print(
            f"\n[3/3] Migrating "
            f"{len(employees)} employees..."
        )

        migrate_employees(
            cursor,
            employees
        )

        # ----------------------------------------------------
        # Commit
        # ----------------------------------------------------

        connection.commit()

        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)

        print(
            f"Employees migrated: "
            f"{len(employees)}"
        )

        print(
            f"Rows skipped: "
            f"{len(failed_rows)}"
        )

    except KeyboardInterrupt:

        print(
            "\n\nMigration interrupted by user."
        )

        connection.rollback()

        print(
            "Transaction rolled back. "
            "No partial migration was committed."
        )

    except Exception as error:

        connection.rollback()

        print(
            "\nMigration failed."
        )

        print(
            f"Error: {error}"
        )

        print(
            "Transaction rolled back."
        )

        raise

    finally:

        cursor.close()
        connection.close()

        print(
            "\nAlloyDB connection closed."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()