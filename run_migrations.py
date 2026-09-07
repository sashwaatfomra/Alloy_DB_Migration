import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

MIGRATIONS = [
    ("Employee Migration", BASE_DIR / "migrate_emp_db.py"),
    ("Project Migration", BASE_DIR / "migrate_project_db.py"),
    ("Project Members Migration", BASE_DIR / "migrate_project_members.py"),
    ("Mentorship Plan Migration", BASE_DIR / "migrate_mentorship_plan.py"),
]

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


# ============================================================
# RUN MIGRATION
# ============================================================

def run_migration(name, script, log_file):

    print("\n" + "=" * 60)
    print(f"STARTING: {name}")
    print("=" * 60)

    start_time = datetime.now()

    log_file.write("\n" + "=" * 60 + "\n")
    log_file.write(f"STARTING: {name}\n")
    log_file.write(f"Script: {script}\n")
    log_file.write(f"Started: {start_time}\n")
    log_file.write("=" * 60 + "\n")
    log_file.flush()

    result = subprocess.run(
        [sys.executable, str(script)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=BASE_DIR,
    )

    duration = datetime.now() - start_time

    if result.returncode != 0:

        print("\n" + "!" * 60)
        print(f"FAILED: {name}")
        print(f"Script: {script}")
        print(f"Duration: {duration}")
        print("!" * 60)

        log_file.write(f"\nFAILED: {name}\n")
        log_file.write(f"Duration: {duration}\n")
        log_file.flush()

        return False

    print("\n" + "-" * 60)
    print(f"COMPLETED: {name}")
    print(f"Duration: {duration}")
    print("-" * 60)

    log_file.write(f"\nCOMPLETED: {name}\n")
    log_file.write(f"Duration: {duration}\n")
    log_file.flush()

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    overall_start = datetime.now()

    timestamp = overall_start.strftime("%Y%m%d_%H%M%S")

    log_path = LOG_DIR / f"migration_{timestamp}.log"

    print("=" * 60)
    print("ALLOYDB DATA MIGRATION RUNNER")
    print("=" * 60)

    print(
        f"Started: "
        f"{overall_start.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    print(f"Log file: {log_path}")

    with open(
        log_path,
        "w",
        encoding="utf-8"
    ) as log_file:

        log_file.write("=" * 60 + "\n")
        log_file.write("ALLOYDB DATA MIGRATION RUNNER\n")
        log_file.write("=" * 60 + "\n")

        log_file.write(
            f"Started: "
            f"{overall_start.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        successful = []
        failed = []

        # ----------------------------------------------------
        # Run migrations sequentially
        # ----------------------------------------------------

        for name, script in MIGRATIONS:

            success = run_migration(
                name,
                script,
                log_file
            )

            if success:

                successful.append(name)

            else:

                failed.append(name)

                print(
                    "\nMigration pipeline stopped because "
                    "a migration failed."
                )

                log_file.write(
                    "\nMigration pipeline stopped because "
                    "a migration failed.\n"
                )

                break

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        overall_duration = (
            datetime.now() - overall_start
        )

        print("\n" + "=" * 60)
        print("MIGRATION RUN SUMMARY")
        print("=" * 60)

        print(
            f"Successful: {len(successful)}"
        )

        for migration in successful:
            print(f"  ✓ {migration}")

        print(
            f"Failed: {len(failed)}"
        )

        for migration in failed:
            print(f"  ✗ {migration}")

        print(
            f"\nTotal duration: "
            f"{overall_duration}"
        )

        print(
            f"Log saved to: {log_path}"
        )

        print("=" * 60)

        log_file.write(
            "\n" + "=" * 60 + "\n"
        )

        log_file.write(
            "MIGRATION RUN SUMMARY\n"
        )

        log_file.write(
            "=" * 60 + "\n"
        )

        log_file.write(
            f"Successful: {len(successful)}\n"
        )

        for migration in successful:

            log_file.write(
                f"  ✓ {migration}\n"
            )

        log_file.write(
            f"Failed: {len(failed)}\n"
        )

        for migration in failed:

            log_file.write(
                f"  ✗ {migration}\n"
            )

        log_file.write(
            f"\nTotal duration: "
            f"{overall_duration}\n"
        )

        log_file.write(
            f"Log saved to: {log_path}\n"
        )

        log_file.write(
            "=" * 60 + "\n"
        )

        if failed:

            log_file.write(
                "MIGRATION RUN FAILED\n"
            )

            sys.exit(1)

        log_file.write(
            "ALL MIGRATIONS COMPLETED SUCCESSFULLY\n"
        )

    print(
        "\nALL MIGRATIONS COMPLETED SUCCESSFULLY"
    )


if __name__ == "__main__":
    main()