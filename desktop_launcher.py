import threading
import time
import webview

from app import app, db, ensure_attendance_schema, ensure_billing_history_schema, ensure_salary_history_schema, start_attendance_cronjob

def run_flask():
    with app.app_context():
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



'''pyinstaller --onefile --noconsole --icon "E:\Alpha fitness gym\mygym\static\logo.ico" --add-data "templates;templates" --add-data "static;static" --add-data ".env;." desktop_launcher.py'''