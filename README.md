# Alloy DB Migration

This repository contains simple Python scripts to run data migrations into Alloy DB.

**Purpose:** provide small, focused migration scripts and helpers to import or update project, employee, and mentorship-plan data.

**Contents:**
- `migrate_emp_db.py` - migrate employee records
- `migrate_project_db.py` - migrate project records
- `migrate_project_members.py` - migrate project membership relations
- `migrate_mentorship_plan.py` - migrate mentorship plan data
- `check_status.py` - verify migration status / sanity checks
- `run_migrations.py` - orchestration script to run multiple migrations
- `service-account.json` - service account credentials (Google Cloud)

**Prerequisites**
- Python 3.9+ (or compatible 3.x)
- A Google Cloud service account JSON with necessary permissions (if using Alloy DB connections that require it)
- Network access to the Alloy DB instance

**Environment**
Create a `.env` file in the repository root containing any required connection values (example keys shown):

DB_HOST=your-alloy-db-host
DB_PORT=5432
DB_NAME=your_database
DB_USER=your_user
DB_PASSWORD=your_password

If your setup requires Google IAM authentication, place the service account JSON at `service-account.json`.

**Usage**
Run a single migration script directly:

```bash
python migrate_emp_db.py
python migrate_project_db.py
python migrate_project_members.py
python migrate_mentorship_plan.py
```

Or run the orchestrator to execute a sequence of migrations:

```bash
python run_migrations.py
```

Use `check_status.py` to run quick verification checks after migrations:

```bash
python check_status.py
```

**Logs**
Logs are written to the `logs/` directory. Inspect the latest log files there for errors and progress information.

**Tips & Troubleshooting**
- Verify `.env` variables are correct and the DB is reachable.
- Ensure `service-account.json` (if used) has correct permissions and the environment variable `GOOGLE_APPLICATION_CREDENTIALS` is set when needed.
- Check `logs/` for stack traces if a script fails.

**Contributing**
Open issues or PRs for improvements. Keep migration scripts small and idempotent where possible.

**License**
This project does not include a license file; add one if you intend to open-source the code.
