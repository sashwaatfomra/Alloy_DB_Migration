import gspread
import psycopg2
from google.oauth2.service_account import Credentials
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

GOOGLE_SHEET_ID = "1i7aek11iTpiladPmJjT_PkoyGlaDvhqHrAan8IDlrLo"

WORKSHEET_NAME = "project_members_table"

SERVICE_ACCOUNT_FILE = "service-account.json"

# Project IDs are now VARCHAR values such as PRJ001, PRJ016, PRJ122
MARKETING_PROJECT_ID = "PRJ016"


# ============================================================
# ALLOYDB CONFIGURATION
# ============================================================

DB_HOST = "35.239.110.182"
DB_NAME = "new_db"
DB_USER = "int-user"
DB_PASSWORD = "5x;g?3<0_CvNK*Oi"


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_to_google_sheet():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    ]

    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes
    )

    gc = gspread.authorize(credentials)

    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

    worksheet = spreadsheet.worksheet(
        WORKSHEET_NAME
    )

    return worksheet


# ============================================================
# DATA CLEANING
# ============================================================

def clean_string(value):

    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    return value


def parse_project_id(value):
    """
    Project IDs are now stored as VARCHAR in AlloyDB.

    Expected format:
        PRJ001
        PRJ002
        PRJ016
        PRJ120
        PRJ122
    """

    value = clean_string(value)

    if value is None:
        return None

    value = value.upper()

    if not value.startswith("PRJ"):
        raise ValueError(
            f"Invalid project_id: '{value}'. "
            "Expected format PRJ###."
        )

    numeric_part = value[3:]

    if not numeric_part.isdigit():
        raise ValueError(
            f"Invalid project_id: '{value}'. "
            "Expected format PRJ###."
        )

    return value


def parse_member_id(value):

    value = clean_string(value)

    if value is None:
        raise ValueError(
            "project_member_id cannot be blank"
        )

    return int(value)


def parse_allocation_percentage(value):

    value = clean_string(value)

    if value is None:
        return None

    value = value.replace("%", "").strip()

    return float(value)


def parse_date(value):

    value = clean_string(value)

    if value is None:
        return None

    # Google Sheets serial date
    try:
        if value.isdigit():
            serial_date = int(value)

            # Google Sheets uses 1899-12-30 as its base date
            from datetime import timedelta

            return (
                datetime(1899, 12, 30)
                + timedelta(days=serial_date)
            ).date()

    except (ValueError, OverflowError):
        pass

    date_formats = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y"
    ]

    for date_format in date_formats:

        try:
            return datetime.strptime(
                value,
                date_format
            ).date()

        except ValueError:
            pass

    raise ValueError(
        f"Unable to parse allocation_date: {value}"
    )

# ============================================================
# PREPARE RECORDS
# ============================================================

def prepare_records(rows):

    prepared = []

    skipped = []

    print("\nPreparing project member records...")

    for sheet_row_number, row in enumerate(
        rows,
        start=2
    ):

        try:

            member_id = parse_member_id(
                row.get("project_member_id")
            )

            project_id = parse_project_id(
                row.get("project_id")
            )

            employee_techo_id = clean_string(
                row.get("employee_techo_id")
            )

            if not employee_techo_id:

                raise ValueError(
                    "employee_techo_id cannot be blank"
                )

            allocation_date = parse_date(
                row.get("allocation_date")
            )

            allocation_percentage = (
                parse_allocation_percentage(
                    row.get("allocation_percentage")
                )
            )

            prepared.append(
                (
                    member_id,
                    project_id,
                    employee_techo_id,
                    allocation_date,
                    allocation_percentage
                )
            )

        except Exception as error:

            print(
                f"Skipping Sheet row "
                f"{sheet_row_number}: {error}"
            )

            skipped.append(
                (
                    sheet_row_number,
                    str(error)
                )
            )

    print(
        f"Valid records: {len(prepared)}"
    )

    print(
        f"Skipped records: {len(skipped)}"
    )

    return prepared, skipped


# ============================================================
# VALIDATE PROJECT REFERENCES
# ============================================================

def validate_project_ids(cursor, records):

    project_ids = set()

    for record in records:

        project_id = record[1]

        if project_id is not None:
            project_ids.add(project_id)

    if not project_ids:
        return

    cursor.execute(
        """
        SELECT project_id
        FROM public.project
        WHERE project_id = ANY(%s);
        """,
        (list(project_ids),)
    )

    existing_ids = {
        row[0]
        for row in cursor.fetchall()
    }

    missing_ids = project_ids - existing_ids

    if missing_ids:

        raise ValueError(
            "These project IDs from the Sheet do not exist "
            "in public.project: "
            f"{sorted(missing_ids)}"
        )

    print(
        f"Project references validated: "
        f"{len(existing_ids)} project IDs"
    )


# ============================================================
# MIGRATE
# ============================================================

def migrate_records(records):

    print("\nConnecting to AlloyDB...")

    connection = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode="require",
        connect_timeout=30
    )

    cursor = connection.cursor()

    print("AlloyDB connected successfully.")

    try:

        # ----------------------------------------------------
        # Verify project_members structure
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'project_members'
            ORDER BY ordinal_position;
            """
        )

        columns = [
            row[0]
            for row in cursor.fetchall()
        ]

        print("\nproject_members columns:")
        print(columns)

        required_columns = [
            "project_member_id",
            "project_id",
            "employee_techo_id",
            "allocation_date",
            "allocation_percentage"
        ]

        for column in required_columns:

            if column not in columns:

                raise ValueError(
                    f"Missing required column: {column}"
                )

        # ----------------------------------------------------
        # Validate project IDs
        # ----------------------------------------------------

        validate_project_ids(
            cursor,
            records
        )

        # ----------------------------------------------------
        # Insert / Update
        # ----------------------------------------------------

        print(
            f"\nMigrating "
            f"{len(records)} project members..."
        )

        for record in records:

            (
                member_id,
                project_id,
                employee_techo_id,
                allocation_date,
                allocation_percentage
            ) = record

            cursor.execute(
                """
                INSERT INTO public.project_members (
                    project_member_id,
                    project_id,
                    employee_techo_id,
                    allocation_date,
                    allocation_percentage
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (project_member_id)
                DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    employee_techo_id = EXCLUDED.employee_techo_id,
                    allocation_date = EXCLUDED.allocation_date,
                    allocation_percentage =
                        EXCLUDED.allocation_percentage;
                """,
                (
                    member_id,
                    project_id,
                    employee_techo_id,
                    allocation_date,
                    allocation_percentage
                )
            )

        connection.commit()

        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)

        print(
            f"Records migrated: {len(records)}"
        )

        # ----------------------------------------------------
        # Verification
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.project_members;
            """
        )

        total = cursor.fetchone()[0]

        print(
            f"Total project members in AlloyDB: {total}"
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.project_members
            WHERE project_id IS NULL;
            """
        )

        null_projects = cursor.fetchone()[0]

        print(
            f"Members with no project: {null_projects}"
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.project_members
            WHERE project_id = %s;
            """,
            (MARKETING_PROJECT_ID,)
        )

        marketing_count = cursor.fetchone()[0]

        print(
            f"Members assigned to Marketing "
            f"({MARKETING_PROJECT_ID}): "
            f"{marketing_count}"
        )

    except Exception as error:

        connection.rollback()

        print("\n" + "=" * 60)
        print("MIGRATION FAILED")
        print("=" * 60)

        print(f"\nError: {error}")

        print("\nTransaction rolled back.")

        raise

    finally:

        cursor.close()
        connection.close()

        print("\nAlloyDB connection closed.")


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("PROJECT MEMBERS DATABASE MIGRATION")
    print("Google Sheets -> AlloyDB")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. Google Sheet
    # --------------------------------------------------------

    print(
        "\n[1/3] Connecting to Google Sheets..."
    )

    worksheet = connect_to_google_sheet()

    print(
        "Google Sheet connected successfully."
    )

    rows = worksheet.get_all_records()

    print(
        f"Rows found: {len(rows)}"
    )

    if not rows:

        raise ValueError(
            "No records found in Google Sheet."
        )

    print("\nSheet columns:")

    print(
        list(rows[0].keys())
    )

    # --------------------------------------------------------
    # 2. Prepare
    # --------------------------------------------------------

    prepared_records, skipped = prepare_records(
        rows
    )

    # --------------------------------------------------------
    # 3. Migrate
    # --------------------------------------------------------

    migrate_records(
        prepared_records
    )

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("PROJECT MEMBERS MIGRATION COMPLETE")
    print("=" * 60)

    print(
        f"Sheet rows: {len(rows)}"
    )

    print(
        f"Migrated: {len(prepared_records)}"
    )

    print(
        f"Skipped: {len(skipped)}"
    )


if __name__ == "__main__":
    main()