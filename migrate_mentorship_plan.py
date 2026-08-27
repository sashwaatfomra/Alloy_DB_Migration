import json
import uuid
from datetime import datetime, timezone

import gspread
import psycopg2
from psycopg2.extras import execute_values, Json
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

SERVICE_ACCOUNT_FILE = "service-account.json"

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1rAfiPmCm6VjtcYGDrI82XLWemm7fDgM1g5FMY6cdYDc/edit"
WORKSHEET_NAME = "Belting Upskilling"

DB_HOST = "35.239.110.182"
DB_PORT = "5432"
DB_NAME = "new_db"
DB_USER = "int-user"
DB_PASSWORD = "5x;g?3<0_CvNK*Oi"

TABLE_NAME = "mentorship_plan"


# ============================================================
# GOOGLE SHEETS
# ============================================================

def read_google_sheet():
    print("\n[1/4] Connecting to Google Sheets...")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes,
    )

    gc = gspread.authorize(credentials)

    sheet = gc.open_by_url(SPREADSHEET_URL).worksheet(WORKSHEET_NAME)

    rows = sheet.get_all_records()

    print("Google Sheet connected successfully.")
    print(f"Rows found: {len(rows)}")

    if not rows:
        raise RuntimeError("The sheet is empty.")

    print("\nSheet columns:")
    print(list(rows[0].keys()))

    return rows


# ============================================================
# ALLOYDB CONNECTION
# ============================================================

def connect_to_alloydb():
    print("\n[2/4] Connecting to AlloyDB...")

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
# FETCH EMPLOYEE NAME -> ID MAP
# ============================================================

def fetch_name_to_id_map(cursor):
    print("\n[3/4] Fetching employee data to map names to IDs...")

    cursor.execute("SELECT techo_id, work_email FROM public.emp_db;")

    rows = cursor.fetchall()

    name_to_id = {work_email: techo_id for techo_id, work_email in rows}

    print(f"Loaded {len(name_to_id)} employee email mappings.")

    return name_to_id


# ============================================================
# FETCH EXISTING PLANS  (mentor + mentee) -> plan_id
# ============================================================

def fetch_existing_plans(cursor):
    """
    Build a lookup of (mentor_techo_id, mentee_techo_id) -> plan_id
    for every plan already in the database.

    This lets us reuse the same plan_id on subsequent runs so that
    ON CONFLICT (plan_id) correctly updates instead of duplicating.
    """

    cursor.execute(
        """
        SELECT plan_id, mentor_techo_id, mentee_techo_id
        FROM public.mentorship_plan;
        """
    )

    existing = {
        (mentor_id, mentee_id): plan_id
        for plan_id, mentor_id, mentee_id in cursor.fetchall()
    }

    print(f"Found {len(existing)} existing mentorship plan(s) in AlloyDB.")

    return existing


# ============================================================
# DATA TRANSFORMATION
# ============================================================

def parse_date(value):
    """
    Try to parse a date string into a Python date object.
    Returns None if the value is empty or cannot be parsed
    (e.g. freeform text like 'Sept 4th week').
    """

    if not value or not isinstance(value, str) or not value.strip():
        return None

    date_formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]

    from datetime import date as _date
    for fmt in date_formats:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue

    # Value could not be parsed — warn and store NULL
    print(f"  WARNING: Could not parse target_completion_date '{value}' — storing NULL.")
    return None


def build_feedback_json(strengths_text, improvements_text, timestamp):
    """
    Parse bullet-separated Strengths and Improvements strings
    and build the JSONB feedback_data structure.
    Logic is identical to the original script.
    """

    # Parse Strengths
    strengths_list = []
    if strengths_text and isinstance(strengths_text, str):
        strengths_list = [
            s.strip()
            for s in strengths_text.split("•")
            if s.strip()
        ]

    # Parse Improvements into focus_areas
    focus_areas = []
    if improvements_text and isinstance(improvements_text, str):
        improvements_list = [
            i.strip()
            for i in improvements_text.split("•")
            if i.strip()
        ]
        for imp in improvements_list:
            focus_areas.append(
                {
                    "id": f"gap_{uuid.uuid4().hex[:6]}",
                    "text": imp,
                    "status": "OPEN",
                    "mentee_justification": None,
                    "submitted_at": timestamp,
                    "resolved_at": None,
                }
            )

    return json.dumps(
        {
            "strengths": strengths_list,
            "focus_areas": focus_areas,
        }
    )


def prepare_records(rows, name_to_id, existing_plans):
    print("\nTransforming data and building JSONB structures...")

    current_time = datetime.now(timezone.utc)
    current_time_iso = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    prepared = []
    skipped = []
    unmatched_names = []

    for row_number, row in enumerate(rows, start=2):
        try:
            mentor_name = row.get("Mentor Email", "")
            mentee_name = row.get("Mentee Email", "")

            mentor_techo_id = name_to_id.get(mentor_name)
            mentee_techo_id = name_to_id.get(mentee_name)

            if mentor_techo_id is None:
                unmatched_names.append(
                    f"Row {row_number}: Mentor '{mentor_name}' not found in emp_db"
                )

            if mentee_techo_id is None:
                unmatched_names.append(
                    f"Row {row_number}: Mentee '{mentee_name}' not found in emp_db"
                )

            # Reuse the existing plan_id if this mentor-mentee pair
            # already exists, otherwise generate a new one.
            pair_key = (mentor_techo_id, mentee_techo_id)
            plan_id = existing_plans.get(pair_key) or str(uuid.uuid4())
            current_belt           = row.get("Current Belt") or None
            target_belt            = row.get("Target Belt") or None
            status                 = row.get("Status") or None
            target_completion_date = parse_date(row.get("Target Completion Date", ""))
            notes                  = row.get("Notes") or None
            risks_dependencies     = row.get("Risks / Dependencies") or None
            is_active              = True
            created_at             = current_time
            updated_at             = current_time

            feedback_data = build_feedback_json(
                row.get("Strengths", ""),
                row.get("Improvements", ""),
                current_time_iso,
            )

            prepared.append(
                (
                    plan_id,
                    mentor_techo_id,
                    mentee_techo_id,
                    current_belt,
                    target_belt,
                    status,
                    target_completion_date,
                    notes,
                    risks_dependencies,
                    is_active,
                    created_at,
                    updated_at,
                    Json(json.loads(feedback_data)),
                )
            )

        except Exception as error:
            print(f"Skipping Sheet row {row_number}: {error}")
            skipped.append((row_number, str(error)))

    if unmatched_names:
        print("\nWARNING: Some names did not match emp_db:")
        for msg in unmatched_names:
            print(f"  {msg}")

    print(f"Valid records:   {len(prepared)}")
    print(f"Skipped records: {len(skipped)}")

    return prepared, skipped


# ============================================================
# MIGRATE
# ============================================================

def migrate_records(cursor, records):
    query = """
        INSERT INTO public.mentorship_plan (
            plan_id,
            mentor_techo_id,
            mentee_techo_id,
            current_belt,
            target_belt,
            status,
            target_completion_date,
            notes,
            risks_dependencies,
            is_active,
            created_at,
            updated_at,
            feedback_data
        )
        VALUES %s

        ON CONFLICT (plan_id)
        DO UPDATE SET
            mentor_techo_id        = EXCLUDED.mentor_techo_id,
            mentee_techo_id        = EXCLUDED.mentee_techo_id,
            current_belt           = EXCLUDED.current_belt,
            target_belt            = EXCLUDED.target_belt,
            status                 = EXCLUDED.status,
            target_completion_date = EXCLUDED.target_completion_date,
            notes                  = EXCLUDED.notes,
            risks_dependencies     = EXCLUDED.risks_dependencies,
            is_active              = EXCLUDED.is_active,
            updated_at             = CURRENT_TIMESTAMP,
            feedback_data          = EXCLUDED.feedback_data;
    """

    execute_values(
        cursor,
        query,
        records,
        page_size=100,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("MENTORSHIP PLAN MIGRATION")
    print("Google Sheets -> AlloyDB")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. Read Google Sheet
    # --------------------------------------------------------

    rows = read_google_sheet()

    # --------------------------------------------------------
    # 2. Connect to AlloyDB
    # --------------------------------------------------------

    connection = connect_to_alloydb()
    cursor = connection.cursor()

    try:

        # ----------------------------------------------------
        # 3. Fetch employee name map
        # ----------------------------------------------------

        name_to_id = fetch_name_to_id_map(cursor)

        existing_plans = fetch_existing_plans(cursor)

        # ----------------------------------------------------
        # 4. Transform data
        # ----------------------------------------------------

        print("\n[4/4] Preparing mentorship plan records...")

        prepared_records, skipped = prepare_records(rows, name_to_id, existing_plans)

        if not prepared_records:
            raise RuntimeError(
                "No valid mentorship plan records available for migration."
            )

        # ----------------------------------------------------
        # 5. Insert
        # ----------------------------------------------------

        print(f"\nMigrating {len(prepared_records)} mentorship plan records...")

        migrate_records(cursor, prepared_records)

        connection.commit()

        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)

        # ----------------------------------------------------
        # Verification
        # ----------------------------------------------------

        cursor.execute("SELECT COUNT(*) FROM public.mentorship_plan;")
        total = cursor.fetchone()[0]
        print(f"Total records in AlloyDB: {total}")
        print(f"Records migrated: {len(prepared_records)}")
        print(f"Rows skipped:     {len(skipped)}")

    except KeyboardInterrupt:
        print("\n\nMigration interrupted by user.")
        connection.rollback()
        print("Transaction rolled back. No partial migration was committed.")

    except Exception as error:
        connection.rollback()
        print("\n" + "=" * 60)
        print("MIGRATION FAILED")
        print("=" * 60)
        print(f"\nError: {error}")
        print("Transaction rolled back.")
        raise

    finally:
        cursor.close()
        connection.close()
        print("\nAlloyDB connection closed.")


if __name__ == "__main__":
    main()