import csv
import sys
from datetime import datetime

import pymysql

DB_CONFIG = {
    "host": "148.163.100.132",
    "user": "mygymlahore_admin_alphafitnessgym",
    "password": "Waqas@0336",
    "database": "mygymlahore_alphafitnessgym",
    "port": 3306,
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.Cursor,
    "autocommit": False,
}

TABLE_NAME = "customer"
DEFAULT_CSV_PATH = r"E:\Alpha fitness gym\mygym\customeralpha.csv"

COLUMNS = [
    "membership_no", "admission_date", "type", "package_id", "status", "billing_date",
    "name", "email", "father_or_husband", "cnic", "gender", "marital_status",
    "blood_group", "dob", "height", "weight", "waist", "profession", "nationality",
    "address", "phone", "emergency_contact", "package", "personal_training_time",
    "trainer", "bmi_test", "bmi_value", "illnesses", "illness_other", "join_reasons",
    "terms_accepted", "thumb_id", "created_at", "updated_at", "discount_amount"
]

DATE_COLUMNS = {"admission_date", "billing_date", "dob", "created_at", "updated_at"}

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    {', '.join(COLUMNS)}
) VALUES (
    {', '.join(['%s'] * len(COLUMNS))}
)
"""


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    return value


def parse_date(value):
    value = clean(value)
    if not value:
        return None

    formats = [
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d-%b-%y",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%d/%b/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return value


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV_PATH

    conn = pymysql.connect(**DB_CONFIG)
    inserted = 0
    failed = 0

    try:
        with conn.cursor() as cursor:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)

                for row_num, row in enumerate(reader, start=1):
                    values = []
                    for col in COLUMNS:
                        value = row.get(col)
                        if col in DATE_COLUMNS:
                            value = parse_date(value)
                        else:
                            value = clean(value)
                        values.append(value)

                    try:
                        cursor.execute(INSERT_SQL, values)
                        inserted += 1

                        if inserted % 100 == 0:
                            conn.commit()
                            print(f"{inserted} completed")

                    except Exception as e:
                        failed += 1
                        conn.rollback()
                        print(f"Row {row_num} failed: {e}")

                conn.commit()

        print(f"Done. Inserted: {inserted}, Failed: {failed}")

    finally:
        conn.close()
