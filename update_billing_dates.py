"""
Update customer.billing_date from billing_update.csv by membership_no.

Reads membership_no + billing_date from CSV, converts dates to yyyy-mm-dd,
then updates customer.billing_date WHERE membership_no matches.
"""
import csv
import sys
from datetime import datetime

import pymysql

# Unbuffered console output
print = lambda *a, **k: (__import__("builtins").print(*a, **k, flush=True))

DB_CONFIG = {
    "host": "148.163.100.132",
    "user": "mygymlahore_admin_alphafitnessgym",
    "password": "Waqas@0335",
    "database": "mygymlahore_alphafitnessgym",
    "port": 3306,
    "charset": "utf8mb4",
    "connect_timeout": 30,
    "read_timeout": 120,
    "write_timeout": 120,
    "cursorclass": pymysql.cursors.Cursor,
    "autocommit": False,
}

DEFAULT_CSV_PATH = r"E:\Alpha fitness gym\mygym\billing_update.csv"

UPDATE_SQL = """
UPDATE customer
SET billing_date = %s, updated_at = NOW()
WHERE membership_no = %s
"""


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def parse_date(value):
    """
    Convert CSV date to MySQL format yyyy-mm-dd.

    billing_update.csv uses m/d/yyyy (e.g. 2/24/2026 = 24 Feb).
    That is required because values like 2/24/2026 are invalid as dd/mm/yyyy
    (month cannot be 24). Also accepts true dd/mm/yyyy and yyyy-mm-dd.
    """
    value = clean(value)
    if not value:
        return None

    # Already MySQL format
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Slash / dash numeric dates: decide order from the numbers
    for sep in ("/", "-"):
        if sep not in value:
            continue
        parts = value.split(sep)
        if len(parts) != 3:
            continue
        try:
            a, b, y = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if y < 100:
            y += 2000

        # Prefer m/d/yyyy for this CSV; fall back to d/m when month would be invalid
        candidates = [(a, b, y), (b, a, y)]  # (month, day, year) tries
        # If first number > 12 it must be day → d/m/yyyy
        if a > 12 and b <= 12:
            candidates = [(b, a, y)]
        # If second number > 12 it must be day → m/d/yyyy
        elif b > 12 and a <= 12:
            candidates = [(a, b, y)]

        for month, day, year in candidates:
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                continue

    formats = [
        "%d-%b-%y",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%d/%b/%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def load_csv_rows(csv_path):
    rows = []
    skipped = 0
    with open(csv_path, "r", encoding="cp1252", errors="replace", newline="") as f:
        for row_num, row in enumerate(csv.DictReader(f), start=2):
            membership_no = clean(row.get("membership_no"))
            raw_date = row.get("billing_date")
            billing_date = parse_date(raw_date)

            if not membership_no or not billing_date:
                skipped += 1
                print(
                    f"Row {row_num}: skipped "
                    f"(membership_no={membership_no!r}, date={raw_date!r})"
                )
                continue

            rows.append((billing_date, membership_no))
    return rows, skipped


def get_connection(retries=8, base_sleep=3):
    import time

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return pymysql.connect(**DB_CONFIG)
        except Exception as e:
            last_err = e
            wait = min(base_sleep * attempt, 30)
            print(f"Connect failed ({attempt}/{retries}): {e}")
            print(f"Waiting {wait}s before retry ...")
            time.sleep(wait)
    raise last_err


def connection_alive(conn):
    try:
        conn.ping(reconnect=True)
        return True
    except Exception:
        return False


def ensure_connection(conn):
    if conn is not None and connection_alive(conn):
        return conn
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    print("Reconnecting to database ...")
    return get_connection()


def main():
    import time

    flags = {"--dry-run", "--force-all"}
    args = [a for a in sys.argv[1:] if a not in flags]
    dry_run = "--dry-run" in sys.argv
    force_all = "--force-all" in sys.argv
    csv_path = args[0] if args else DEFAULT_CSV_PATH

    print(f"Reading {csv_path} ...")
    csv_rows, skipped = load_csv_rows(csv_path)
    print(f"CSV rows ready: {len(csv_rows)} (skipped {skipped})")
    # Show sample conversions
    for sample in csv_rows[:3]:
        print(f"  sample: {sample[1]} -> {sample[0]}")

    print("Connecting to database ...")
    conn = get_connection()

    updated = 0
    unchanged = 0
    not_found = 0
    failed = 0
    missing = []
    to_update = []
    remaining = []

    try:
        with conn.cursor() as cursor:
            print("Loading current billing dates ...")
            cursor.execute("SELECT membership_no, billing_date FROM customer")
            current = {}
            for membership_no, billing_date in cursor.fetchall():
                if hasattr(billing_date, "strftime"):
                    current[membership_no] = billing_date.strftime("%Y-%m-%d")
                elif billing_date is None:
                    current[membership_no] = None
                else:
                    current[membership_no] = str(billing_date)
            print(f"DB customers loaded: {len(current)}")

            for billing_date, membership_no in csv_rows:
                if membership_no not in current:
                    not_found += 1
                    missing.append(membership_no)
                    continue
                if current[membership_no] == billing_date:
                    unchanged += 1
                    if not force_all:
                        continue
                to_update.append((billing_date, membership_no))

            print(f"Will write : {len(to_update)} (force_all={force_all})")
            print(f"Already OK : {unchanged}")
            print(f"Not found  : {not_found}")

        if dry_run:
            for billing_date, membership_no in to_update[:30]:
                print(
                    f"[dry-run] {membership_no}: "
                    f"{current[membership_no]} -> {billing_date}"
                )
        else:
            # One-row commits are slower but survive remote drops/locks better
            abort = False
            total = len(to_update)
            for i, (billing_date, membership_no) in enumerate(to_update, start=1):
                if abort:
                    remaining = to_update[i - 1 :]
                    break
                attempts = 0
                while attempts < 5:
                    attempts += 1
                    try:
                        conn = ensure_connection(conn)
                        with conn.cursor() as cursor:
                            cursor.execute(
                                "SET SESSION innodb_lock_wait_timeout = 10"
                            )
                            cursor.execute(
                                UPDATE_SQL, (billing_date, membership_no)
                            )
                            conn.commit()
                        updated += 1
                        if updated % 25 == 0 or updated == total:
                            print(f"{updated}/{total} saved...")
                        break
                    except Exception as e:
                        err = str(e)
                        print(f"Retry {attempts} {membership_no}: {e}")
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = None
                        if "Lock wait" in err or "1205" in err:
                            time.sleep(3 * attempts)
                        elif attempts >= 5:
                            failed += 1
                            # If host unreachable repeatedly, stop cleanly
                            if "2003" in err or "unreachable" in err.lower():
                                print(
                                    "Too many connection failures — "
                                    "stopping. Re-run script to continue."
                                )
                                remaining = to_update[i - 1 :]
                                abort = True
                            break
                        else:
                            time.sleep(2 * attempts)

                if i % 50 == 0:
                    time.sleep(0.5)

        print("\n===================================")
        print(f"Mode      : {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
        print(f"Saved     : {updated if not dry_run else len(to_update)}")
        print(f"Already OK: {unchanged}")
        print(f"Not found : {not_found}")
        print(f"Skipped   : {skipped}")
        print(f"Failed    : {failed}")
        print(f"Remaining : {len(remaining)}")
        if missing:
            print(f"Missing   : {missing[:20]}")
        print("===================================")

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
