"""
Alpha Fitness Gym — Database Backup & Restore

Usage:
  python db_backup.py backup              Create a full DB backup
  python db_backup.py list                List available backups
  python db_backup.py restore             Restore (interactive pick)
  python db_backup.py restore <file.sql>  Restore a specific backup

Restore behavior:
  1. Drops ALL current tables/data in the live database
  2. Recreates only what exists in the backup file
  3. Any rows/tables added after the backup are removed

Examples:
  python db_backup.py backup
  python db_backup.py restore backups/alphafitness_20260714_231500.sql
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pymysql
from pymysql.constants import FIELD_TYPE

# ========================
# DATABASE CONFIG
# (matches app.py live URI)
# ========================
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "148.163.100.132"),
    "user": os.getenv("DB_USER", "mygymlahore_admin_alphafitnessgym"),
    "password": os.getenv("DB_PASSWORD", "Waqas@0335"),
    "database": os.getenv("DB_NAME", "mygymlahore_alphafitnessgym"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.Cursor,
    "autocommit": False,
}

SCRIPT_DIR = Path(__file__).resolve().parent
BACKUP_DIR = SCRIPT_DIR / "backups"
BINARY_TYPES = {
    FIELD_TYPE.BLOB,
    FIELD_TYPE.TINY_BLOB,
    FIELD_TYPE.MEDIUM_BLOB,
    FIELD_TYPE.LONG_BLOB,
    FIELD_TYPE.BIT,
}


def connect():
    return pymysql.connect(**DB_CONFIG)


def ensure_backup_dir():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def sql_literal(value, is_binary=False):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    # date / time objects (not datetime)
    if type(value).__name__ == "date":
        return f"'{value.isoformat()}'"
    if type(value).__name__ == "timedelta":
        total = int(value.total_seconds())
        hours, rem = divmod(abs(total), 3600)
        minutes, seconds = divmod(rem, 60)
        sign = "-" if total < 0 else ""
        return f"'{sign}{hours:02d}:{minutes:02d}:{seconds:02d}'"
    if type(value).__name__ == "time":
        return f"'{value.isoformat()}'"
    if is_binary or isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return "0x" + raw.hex() if raw else "NULL"
    text = str(value)
    text = (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\x00", "\\0")
    )
    return f"'{text}'"


def quote_ident(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def list_tables(cursor):
    cursor.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
    return [row[0] for row in cursor.fetchall()]


def create_backup(label: str | None = None) -> Path:
    ensure_backup_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    outfile = BACKUP_DIR / f"alphafitness_{stamp}{suffix}.sql"

    print(f"Connecting to {DB_CONFIG['host']}/{DB_CONFIG['database']} ...")
    conn = connect()
    try:
        with conn.cursor() as cursor:
            tables = list_tables(cursor)
            if not tables:
                raise RuntimeError("No tables found in database.")

            print(f"Backing up {len(tables)} table(s) -> {outfile.name}")

            with outfile.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write("-- Alpha Fitness Gym DB Backup\n")
                fh.write(f"-- Created: {datetime.now().isoformat(timespec='seconds')}\n")
                fh.write(f"-- Host: {DB_CONFIG['host']}\n")
                fh.write(f"-- Database: {DB_CONFIG['database']}\n")
                fh.write("SET NAMES utf8mb4;\n")
                fh.write("SET FOREIGN_KEY_CHECKS=0;\n")
                fh.write("SET UNIQUE_CHECKS=0;\n")
                fh.write("SET SQL_MODE='NO_AUTO_VALUE_ON_ZERO';\n\n")

                for table in tables:
                    qtable = quote_ident(table)
                    print(f"  - {table}")

                    cursor.execute(f"SHOW CREATE TABLE {qtable}")
                    create_sql = cursor.fetchone()[1]

                    fh.write(f"-- ----------------------------\n")
                    fh.write(f"-- Table structure for {table}\n")
                    fh.write(f"-- ----------------------------\n")
                    fh.write(f"DROP TABLE IF EXISTS {qtable};\n")
                    fh.write(f"{create_sql};\n\n")

                    cursor.execute(f"SELECT * FROM {qtable}")
                    rows = cursor.fetchall()
                    if not rows:
                        fh.write(f"-- No data in {table}\n\n")
                        continue

                    col_info = cursor.description
                    col_names = [quote_ident(c[0]) for c in col_info]
                    binary_flags = [c[1] in BINARY_TYPES for c in col_info]

                    fh.write(f"-- ----------------------------\n")
                    fh.write(f"-- Data for {table} ({len(rows)} rows)\n")
                    fh.write(f"-- ----------------------------\n")

                    batch_size = 200
                    for start in range(0, len(rows), batch_size):
                        batch = rows[start:start + batch_size]
                        values_sql = []
                        for row in batch:
                            literals = [
                                sql_literal(val, is_binary=binary_flags[i])
                                for i, val in enumerate(row)
                            ]
                            values_sql.append("(" + ", ".join(literals) + ")")
                        fh.write(
                            f"INSERT INTO {qtable} ({', '.join(col_names)}) VALUES\n"
                        )
                        fh.write(",\n".join(values_sql))
                        fh.write(";\n")
                    fh.write("\n")

                fh.write("SET FOREIGN_KEY_CHECKS=1;\n")
                fh.write("SET UNIQUE_CHECKS=1;\n")
                fh.write("-- Backup complete\n")

        size_mb = outfile.stat().st_size / (1024 * 1024)
        print(f"\nBackup saved: {outfile}")
        print(f"Size: {size_mb:.2f} MB")
        return outfile
    finally:
        conn.close()


def list_backups() -> list[Path]:
    ensure_backup_dir()
    files = sorted(BACKUP_DIR.glob("alphafitness_*.sql"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("No backups found in:", BACKUP_DIR)
        return []
    print(f"Available backups in {BACKUP_DIR}:\n")
    for i, path in enumerate(files, start=1):
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  {i}. {path.name}  ({size_mb:.2f} MB, {mtime})")
    return files


def split_sql_statements(sql_text: str) -> list[str]:
    """
    Split SQL dump into statements, respecting quotes and comments.
    """
    statements = []
    buf = []
    in_single = False
    in_double = False
    in_backtick = False
    i = 0
    length = len(sql_text)

    while i < length:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < length else ""

        # Line comment --
        if not in_single and not in_double and not in_backtick and ch == "-" and nxt == "-":
            while i < length and sql_text[i] not in "\n\r":
                i += 1
            continue

        # Block comment /* */
        if not in_single and not in_double and not in_backtick and ch == "/" and nxt == "*":
            i += 2
            while i < length - 1 and not (sql_text[i] == "*" and sql_text[i + 1] == "/"):
                i += 1
            i += 2
            continue

        if ch == "'" and not in_double and not in_backtick:
            if in_single and nxt == "'":
                buf.append("''")
                i += 2
                continue
            # escaped \'
            if in_single and len(buf) >= 1 and buf[-1] == "\\":
                buf.append(ch)
                i += 1
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        if ch == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
            buf.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double and not in_backtick:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def resolve_backup_path(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        if not path.is_absolute():
            # allow relative to CWD or script backups/
            candidates = [
                Path.cwd() / path,
                SCRIPT_DIR / path,
                BACKUP_DIR / path.name,
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate.resolve()
            raise FileNotFoundError(f"Backup file not found: {path_arg}")
        if not path.exists():
            raise FileNotFoundError(f"Backup file not found: {path}")
        return path.resolve()

    files = list_backups()
    if not files:
        raise FileNotFoundError("No backup files available to restore.")

    choice = input("\nEnter backup number to restore (or blank to cancel): ").strip()
    if not choice:
        raise SystemExit("Restore cancelled.")
    try:
        idx = int(choice)
    except ValueError as exc:
        raise ValueError("Invalid selection.") from exc
    if idx < 1 or idx > len(files):
        raise ValueError("Selection out of range.")
    return files[idx - 1]


def extract_tables_from_backup(sql_text: str) -> list[str]:
    """Table names referenced by DROP/CREATE in the backup dump."""
    found = []
    seen = set()
    for match in re.finditer(
        r"(?:DROP\s+TABLE\s+IF\s+EXISTS|CREATE\s+TABLE)\s+`?([A-Za-z0-9_]+)`?",
        sql_text,
        flags=re.IGNORECASE,
    ):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found


def wipe_database(cursor, keep_tables: set[str] | None = None):
    """
    Drop every base table in the current database.
    Any table/data not present in the backup will be removed.
    """
    keep_tables = keep_tables or set()
    tables = list_tables(cursor)
    if not tables:
        print("  (database already empty)")
        return

    print(f"  Dropping {len(tables)} existing table(s) ...")
    for table in tables:
        if table in keep_tables:
            continue
        print(f"    - drop {table}")
        cursor.execute(f"DROP TABLE IF EXISTS {quote_ident(table)}")


def restore_backup(backup_path: Path, skip_confirm: bool = False):
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    print(f"\nWARNING: This will WIPE the current database and restore from backup.")
    print(f"  Database : {DB_CONFIG['database']} @ {DB_CONFIG['host']}")
    print(f"  Backup   : {backup_path.name}")
    print("  Effect   : all current data is removed;")
    print("             only data present in the backup will remain;")
    print("             rows/tables added after the backup will be deleted.\n")

    if not skip_confirm:
        confirm = input('Type YES to continue restore: ').strip()
        if confirm != "YES":
            print("Restore cancelled.")
            return

    print("Reading backup file ...")
    sql_text = backup_path.read_text(encoding="utf-8")
    statements = split_sql_statements(sql_text)
    backup_tables = extract_tables_from_backup(sql_text)
    print(f"Backup contains {len(backup_tables)} table(s), {len(statements)} SQL statement(s).")

    conn = connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            cursor.execute("SET UNIQUE_CHECKS=0")
            cursor.execute("SET SQL_MODE='NO_AUTO_VALUE_ON_ZERO'")

            # 1) Clear everything currently in DB (including new post-backup data)
            print("\nStep 1/2: Clearing current database ...")
            wipe_database(cursor)

            # 2) Rebuild exactly from backup
            print("\nStep 2/2: Restoring backup data ...")
            for i, stmt in enumerate(statements, start=1):
                # Skip session toggles already applied / trailing ones that
                # could re-enable FK checks mid-restore if split oddly.
                upper = stmt.strip().upper()
                if upper.startswith("SET FOREIGN_KEY_CHECKS") or upper.startswith("SET UNIQUE_CHECKS"):
                    continue
                try:
                    cursor.execute(stmt)
                except Exception as exc:
                    preview = re.sub(r"\s+", " ", stmt)[:160]
                    raise RuntimeError(
                        f"Failed at statement #{i}: {exc}\nSQL: {preview}..."
                    ) from exc
                if i % 50 == 0 or i == len(statements):
                    print(f"  progress: {i}/{len(statements)}")

            cursor.execute("SET FOREIGN_KEY_CHECKS=1")
            cursor.execute("SET UNIQUE_CHECKS=1")

            # Verify final table set matches backup
            final_tables = set(list_tables(cursor))
            expected = set(backup_tables)
            extras = sorted(final_tables - expected)
            missing = sorted(expected - final_tables)
            if extras:
                print(f"\nRemoving leftover tables not in backup: {', '.join(extras)}")
                for table in extras:
                    cursor.execute(f"DROP TABLE IF EXISTS {quote_ident(table)}")
            if missing:
                print(f"Warning: tables missing after restore: {', '.join(missing)}")

        conn.commit()
        print("\nRestore completed successfully.")
        print("Database now matches the backup (post-backup data removed).")
    except Exception:
        conn.rollback()
        print("\nRestore FAILED. Database was rolled back where possible.")
        raise
    finally:
        conn.close()

def interactive_menu():
    while True:
        print("\n=== Alpha Fitness DB Backup Tool ===")
        print("1) Create backup")
        print("2) List backups")
        print("3) Restore from backup")
        print("4) Exit")
        choice = input("Choose option: ").strip()
        if choice == "1":
            create_backup()
        elif choice == "2":
            list_backups()
        elif choice == "3":
            path = resolve_backup_path(None)
            restore_backup(path)
        elif choice == "4":
            print("Bye.")
            return
        else:
            print("Invalid option.")


def main():
    parser = argparse.ArgumentParser(description="Backup / restore Alpha Fitness MySQL database")
    parser.add_argument(
        "action",
        nargs="?",
        choices=["backup", "restore", "list", "menu"],
        default="menu",
        help="Action to perform (default: interactive menu)",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Backup .sql file path (for restore)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional label appended to backup filename",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip restore confirmation (use carefully)",
    )
    args = parser.parse_args()

    try:
        if args.action == "backup":
            create_backup(label=args.label)
        elif args.action == "list":
            list_backups()
        elif args.action == "restore":
            path = resolve_backup_path(args.path)
            restore_backup(path, skip_confirm=args.yes)
        else:
            interactive_menu()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
