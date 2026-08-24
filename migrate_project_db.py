import gspread
import psycopg2
import requests

from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

GOOGLE_SHEET_ID = "1i7aek11iTpiladPmJjT_PkoyGlaDvhqHrAan8IDlrLo"

WORKSHEET_NAME = "Projects"

SERVICE_ACCOUNT_FILE = "service-account.json"


# ============================================================
# ALLOYDB CONFIGURATION
# ============================================================

DB_HOST = "35.239.110.182"
DB_NAME = "int_db"
DB_USER = "int-user"
DB_PASSWORD = "5x;g?3<0_CvNK*Oi"


# ============================================================
# EMBEDDING CONFIGURATION
# ============================================================

TE_EMBEDDING_AGENT_URL = (
    "https://devllmstudio.creativeworkspace.ai/"
    "cognitive_recollection/embeddings_generator"
)

EMBEDDING_MODEL = "gemini-embedding-001"

EMBEDDING_DIMENSION = 1536

EMBEDDING_TIMEOUT = 60

EMBEDDING_RETRIES = 3


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


# ============================================================
# PROJECT ID
# ============================================================

def parse_project_id(value):

    value = clean_string(value)

    if value is None:
        raise ValueError(
            "Project ID cannot be blank"
        )

    # Project IDs are now VARCHAR.
    #
    # Examples:
    # PRJ001
    # PRJ002
    # PRJ120

    return value


# ============================================================
# PREPARE PROJECT RECORDS
# ============================================================

def prepare_records(rows):

    prepared = []

    skipped = []

    print("\nPreparing project records...")

    for sheet_row_number, row in enumerate(
        rows,
        start=2
    ):

        try:

            project_id = parse_project_id(
                row.get("Project ID")
            )

            project_type = clean_string(
                row.get("Project Type")
            )

            project_name = clean_string(
                row.get("Project Name")
            )

            project_description = clean_string(
                row.get("Project Description")
            )

            project_classification = clean_string(
                row.get("Project Classification")
            )

            pm_name = clean_string(
                row.get("Project Manager")
            )

            pm_email = clean_string(
                row.get("PM Email")
            )

            eo_name = clean_string(
                row.get("Engineering Owner")
            )

            eo_email = clean_string(
                row.get("EO Email")
            )

            if not project_name:

                raise ValueError(
                    "Project Name cannot be blank"
                )

            prepared.append(
                (
                    project_id,
                    project_type,
                    project_name,
                    project_description,
                    project_classification,
                    pm_name,
                    pm_email,
                    eo_name,
                    eo_email
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
        f"Valid project records: "
        f"{len(prepared)}"
    )

    print(
        f"Invalid project records: "
        f"{len(skipped)}"
    )

    return prepared, skipped


# ============================================================
# BUILD EMBEDDING TEXT
# ============================================================

def build_embedding_text(record):

    (
        project_id,
        project_type,
        project_name,
        project_description,
        project_classification,
        pm_name,
        pm_email,
        eo_name,
        eo_email
    ) = record

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Only the requested project fields are embedded.
    #
    # Project ID is intentionally included.
    # PM / EO information is NOT included.
    # --------------------------------------------------------

    embedding_text = f"""
Project ID: {project_id or ""}
Project Name: {project_name or ""}
Project Description: {project_description or ""}
Project Classification: {project_classification or ""}
Project Type: {project_type or ""}
""".strip()

    return embedding_text


# ============================================================
# GENERATE EMBEDDING
# ============================================================

def generate_embedding(text):

    payload = {
        "user_query": text,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION
    }

    last_error = None

    for attempt in range(
        1,
        EMBEDDING_RETRIES + 1
    ):

        try:

            response = requests.post(
                TE_EMBEDDING_AGENT_URL,
                json=payload,
                timeout=EMBEDDING_TIMEOUT
            )

            response.raise_for_status()

            response_data = response.json()

            # ------------------------------------------------
            # Validate API status
            # ------------------------------------------------

            if response_data.get("status") != "success":

                raise ValueError(
                    "Embedding API returned "
                    f"status: "
                    f"{response_data.get('status')}"
                )

            # ------------------------------------------------
            # Extract embedding
            # ------------------------------------------------

            embedding = response_data.get(
                "embedding"
            )

            if embedding is None:

                raise ValueError(
                    "Embedding missing from API response"
                )

            # ------------------------------------------------
            # Validate embedding dimension
            # ------------------------------------------------

            if len(embedding) != EMBEDDING_DIMENSION:

                raise ValueError(
                    "Invalid embedding dimension. "
                    f"Expected {EMBEDDING_DIMENSION}, "
                    f"received {len(embedding)}"
                )

            # ------------------------------------------------
            # Validate values are numeric
            # ------------------------------------------------

            embedding = [
                float(value)
                for value in embedding
            ]

            return embedding

        except Exception as error:

            last_error = error

            print(
                f"Embedding attempt "
                f"{attempt}/{EMBEDDING_RETRIES} failed: "
                f"{error}"
            )

    raise RuntimeError(
        "Embedding generation failed after "
        f"{EMBEDDING_RETRIES} attempts: "
        f"{last_error}"
    )


# ============================================================
# CONVERT EMBEDDING TO PGVECTOR FORMAT
# ============================================================

def embedding_to_vector(embedding):

    return "[" + ",".join(
        str(value)
        for value in embedding
    ) + "]"


# ============================================================
# MIGRATE PROJECTS
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

    print(
        "AlloyDB connected successfully."
    )

    try:

        # ----------------------------------------------------
        # Verify project table structure
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'project'
            ORDER BY ordinal_position;
            """
        )

        columns = cursor.fetchall()

        column_map = {
            row[0]: row[1]
            for row in columns
        }

        required_columns = [
            "project_id",
            "project_name",
            "project_description",
            "project_classification",
            "project_embedding",
            "pm_name",
            "pm_email",
            "eo_name",
            "eo_email",
            "project_type"
        ]

        for column in required_columns:

            if column not in column_map:

                raise ValueError(
                    f"Missing required column: "
                    f"{column}"
                )

        # ----------------------------------------------------
        # Verify Project ID type
        # ----------------------------------------------------

        project_id_type = column_map[
            "project_id"
        ]

        if project_id_type != "character varying":

            raise ValueError(
                "project_id must be VARCHAR. "
                f"Current type: {project_id_type}"
            )

        print(
            "Project table structure validated."
        )

        print(
            "\nProject ID type: "
            f"{project_id_type}"
        )

        # ----------------------------------------------------
        # Migrate each project
        # ----------------------------------------------------

        print(
            f"\nMigrating {len(records)} projects..."
        )

        migrated_count = 0

        for index, record in enumerate(
            records,
            start=1
        ):

            (
                project_id,
                project_type,
                project_name,
                project_description,
                project_classification,
                pm_name,
                pm_email,
                eo_name,
                eo_email
            ) = record

            print(
                f"\n[{index}/{len(records)}] "
                f"Processing {project_id} - "
                f"{project_name}"
            )

            # ------------------------------------------------
            # Build embedding text
            # ------------------------------------------------

            embedding_text = build_embedding_text(
                record
            )

            print(
                "Generating project embedding..."
            )

            # ------------------------------------------------
            # Generate embedding
            # ------------------------------------------------

            embedding = generate_embedding(
                embedding_text
            )

            print(
                "Embedding generated successfully "
                f"({len(embedding)} dimensions)"
            )

            # ------------------------------------------------
            # Convert to pgvector format
            # ------------------------------------------------

            vector_value = embedding_to_vector(
                embedding
            )

            # ------------------------------------------------
            # Insert / Update project
            # ------------------------------------------------

            cursor.execute(
                """
                INSERT INTO public.project (
                    project_id,
                    project_name,
                    project_description,
                    project_classification,
                    project_embedding,
                    pm_name,
                    pm_email,
                    eo_name,
                    eo_email,
                    project_type
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::vector,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (project_id)
                DO UPDATE SET

                    project_name =
                        EXCLUDED.project_name,

                    project_description =
                        EXCLUDED.project_description,

                    project_classification =
                        EXCLUDED.project_classification,

                    project_embedding =
                        EXCLUDED.project_embedding,

                    pm_name =
                        EXCLUDED.pm_name,

                    pm_email =
                        EXCLUDED.pm_email,

                    eo_name =
                        EXCLUDED.eo_name,

                    eo_email =
                        EXCLUDED.eo_email,

                    project_type =
                        EXCLUDED.project_type,

                    updated_at =
                        CURRENT_TIMESTAMP;
                """,
                (
                    project_id,
                    project_name,
                    project_description,
                    project_classification,
                    vector_value,
                    pm_name,
                    pm_email,
                    eo_name,
                    eo_email,
                    project_type
                )
            )

            migrated_count += 1

            print(
                f"Project {project_id} migrated "
                "with embedding."
            )

        # ----------------------------------------------------
        # Commit
        # ----------------------------------------------------

        connection.commit()

        print(
            "\n" + "=" * 60
        )

        print(
            "PROJECT MIGRATION COMPLETED "
            "SUCCESSFULLY"
        )

        print(
            "=" * 60
        )

        print(
            f"Successfully migrated: "
            f"{migrated_count} projects"
        )

        # ----------------------------------------------------
        # Verification
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.project;
            """
        )

        total_projects = cursor.fetchone()[0]

        print(
            f"Total projects in AlloyDB: "
            f"{total_projects}"
        )

        # ----------------------------------------------------
        # Verify embeddings
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.project
            WHERE project_embedding IS NOT NULL;
            """
        )

        embedding_count = cursor.fetchone()[0]

        print(
            f"Projects with embeddings: "
            f"{embedding_count}"
        )

        # ----------------------------------------------------
        # Verify embedding dimensions
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM public.project
            WHERE project_embedding IS NOT NULL
              AND vector_dims(project_embedding) =
                  %s;
            """,
            (EMBEDDING_DIMENSION,)
        )

        valid_embedding_count = (
            cursor.fetchone()[0]
        )

        print(
            f"Projects with valid "
            f"{EMBEDDING_DIMENSION}-dimensional "
            f"embeddings: "
            f"{valid_embedding_count}"
        )

        # ----------------------------------------------------
        # Show first few projects
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                project_id,
                project_name,
                project_type,
                vector_dims(project_embedding)
            FROM public.project
            ORDER BY project_id
            LIMIT 10;
            """
        )

        sample_projects = cursor.fetchall()

        print(
            "\nFirst 10 projects:"
        )

        for row in sample_projects:

            print(
                f"{row[0]} | "
                f"{row[1]} | "
                f"{row[2]} | "
                f"Embedding dimensions: {row[3]}"
            )

    except Exception as error:

        connection.rollback()

        print(
            "\n" + "=" * 60
        )

        print(
            "PROJECT MIGRATION FAILED"
        )

        print(
            "=" * 60
        )

        print(
            f"\nError: {error}"
        )

        print(
            "\nTransaction rolled back."
        )

        raise

    finally:

        cursor.close()
        connection.close()

        print(
            "\nAlloyDB connection closed."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "PROJECT DATABASE MIGRATION"
    )

    print(
        "Google Sheets -> AlloyDB"
    )

    print(
        "Project Data + Embeddings"
    )

    print(
        "=" * 60
    )

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

    print(
        "\nSheet columns:"
    )

    print(
        list(rows[0].keys())
    )

    # --------------------------------------------------------
    # 2. Prepare records
    # --------------------------------------------------------

    prepared_records, skipped = (
        prepare_records(rows)
    )

    if not prepared_records:

        raise ValueError(
            "No valid project records found."
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

    print(
        "\n" + "=" * 60
    )

    print(
        "PROJECT MIGRATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"Sheet rows: {len(rows)}"
    )

    print(
        f"Migrated: {len(prepared_records)}"
    )

    print(
        f"Skipped: {len(skipped)}"
    )

    print(
        "Embeddings generated and stored "
        "in project.project_embedding."
    )


if __name__ == "__main__":
    main()