import os
import sys
import threading
import time
import webview

# Desktop always uses fast local SQLite. MySQL is used only on Backup push.
os.environ["DB_BACKEND"] = "sqlite"

from zk_windows_fix import silence_zk_ping_console
silence_zk_ping_console()

from app import (
    app,
    db,
    ensure_attendance_schema,
    ensure_billing_history_schema,
    ensure_salary_history_schema,
    initialize_local_sqlite_data,
    start_attendance_cronjob,
    start_backup_cronjob,
    SQLITE_DB_PATH,
)
from db_sync import DATA_DIR, BACKUP_DIR, get_app_root


def run_flask():
    # Writable folders next to the .exe (shared dist/)
    root = get_app_root()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    app.logger.info("App root (dist): %s", root)
    app.logger.info("SQLite target: %s", SQLITE_DB_PATH)

    with app.app_context():
        # FIRST: install seed DB if missing/empty (never wipe existing user data)
        try:
            seed_result = initialize_local_sqlite_data()
            app.logger.info(
                "DB init: %s",
                seed_result.get("message") if seed_result else "no result",
            )
        except Exception as exc:
            app.logger.warning("DB init failed: %s", exc)

        db.create_all()
        try:
            ensure_attendance_schema()
        except Exception as exc:
            app.logger.warning(f"Attendance schema sync skipped: {exc}")
        try:
            ensure_billing_history_schema()
        except Exception as exc:
            app.logger.warning(f"Billing history schema sync skipped: {exc}")
        try:
            ensure_salary_history_schema()
        except Exception as exc:
            app.logger.warning(f"Salary history schema sync skipped: {exc}")

    start_attendance_cronjob()
    start_backup_cronjob()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    time.sleep(2)

    webview.create_window(
        "Alpha Fitness Gym",
        "http://127.0.0.1:5000",
        width=1200,
        height=800,
        resizable=True
    )
    webview.start(debug=False)


# ---------------------------------------------------------------------------
# BUILD & SHARE (important — prevents empty DB for end users)
# Run from mygym folder:  .\build_dist.ps1
# Or manually:
#   1) Copy data\mygym_local.db -> seed\mygym_seed.db
#   2) pyinstaller ... --add-data "seed;seed" --add-data "backups;backups" ...
#   3) After build, ALSO copy into dist so users already have the file:
#        mkdir dist\data
#        copy data\mygym_local.db dist\data\mygym_local.db
#        copy seed\mygym_seed.db dist\seed\mygym_seed.db
# Share the whole dist\ folder.
# ---------------------------------------------------------------------------
