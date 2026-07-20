"""
Local SQLite <-> remote MySQL sync for Alpha Fitness Gym.

Desktop app uses SQLite for speed. MySQL on cPanel is the live/cloud copy.
- seed_sqlite_from_mysql: one-time (or manual) pull when local DB is empty
- push_sqlite_to_mysql: full replace of MySQL data from local SQLite
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
BACKUP_DIR = SCRIPT_DIR / "backups"
SYNC_META_PATH = DATA_DIR / "sync_meta.json"
DEFAULT_SEED_DUMP = BACKUP_DIR / "alphafitness_20260720_222616.sql"

# Insert parents first; delete children first (reverse).
TABLE_ORDER = [
    "packages",
    "user",
    "customer",
    "employee",
    "trainer",
    "invoice",
    "billing",
    "billing_history",
    "remaining_amount",
    "expense",
    "salary_history",
    "attendance",
]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def sqlite_uri(db_path: Path | str | None = None) -> str:
    path = Path(db_path) if db_path else (DATA_DIR / "mygym_local.db")
    ensure_data_dir()
    return f"sqlite:///{path.resolve().as_posix()}"


def mysql_uri_from_env() -> str:
    """Build MySQL URI from env, with same defaults as the live cPanel DB."""
    explicit = os.getenv("MYSQL_DATABASE_URI", "").strip()
    if explicit:
        return explicit

    host = os.getenv("DB_HOST", "148.163.100.132")
    user = os.getenv("DB_USER", "mygymlahore_admin_alphafitnessgym")
    password = os.getenv("DB_PASSWORD", "Waqas@0335")
    name = os.getenv("DB_NAME", "mygymlahore_alphafitnessgym2")
    port = os.getenv("DB_PORT", "3306")
    # urllib-quote password for special chars
    from urllib.parse import quote_plus

    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{name}"
    )


def get_engine(uri: str) -> Engine:
    kwargs: dict[str, Any] = {"future": True}
    if uri.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(uri, **kwargs)


def load_sync_meta() -> dict[str, Any]:
    ensure_data_dir()
    if not SYNC_META_PATH.exists():
        return {}
    try:
        return json.loads(SYNC_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sync_meta(meta: dict[str, Any]) -> None:
    ensure_data_dir()
    SYNC_META_PATH.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def hours_since_last_push() -> float | None:
    meta = load_sync_meta()
    last = parse_iso(meta.get("last_push_at"))
    if not last:
        return None
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0


def should_auto_push(interval_hours: float = 24.0) -> bool:
    elapsed = hours_since_last_push()
    if elapsed is None:
        return True
    return elapsed >= interval_hours


def _table_names_present(engine: Engine, names: list[str]) -> list[str]:
    meta = MetaData()
    meta.reflect(bind=engine)
    available = set(meta.tables.keys())
    return [n for n in names if n in available]


def count_rows(engine: Engine, table_name: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar() or 0)


def local_db_is_empty(engine: Engine) -> bool:
    """True when local DB has no meaningful member/user data yet."""
    present = _table_names_present(engine, ["customer", "user", "packages"])
    if not present:
        return True
    for name in present:
        try:
            if count_rows(engine, name) > 0:
                return False
        except Exception:
            continue
    return True


def _disable_fk(conn, dialect: str) -> None:
    if dialect == "mysql":
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    elif dialect == "sqlite":
        conn.execute(text("PRAGMA foreign_keys=OFF"))


def _enable_fk(conn, dialect: str) -> None:
    if dialect == "mysql":
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    elif dialect == "sqlite":
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _mysql_create_to_sqlite(create_sql: str) -> tuple[str, list[str]]:
    """Convert a MySQL CREATE TABLE statement into SQLite DDL + index statements."""
    import re

    index_statements: list[str] = []
    sql = create_sql.strip().rstrip(";")

    # Capture table name
    m = re.search(r"CREATE TABLE\s+`?(\w+)`?\s*\(", sql, re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse CREATE TABLE: {create_sql[:80]}")
    table = m.group(1)

    # Body between first ( and matching last )
    start = sql.index("(")
    depth = 0
    end = None
    for i, ch in enumerate(sql[start:], start):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise ValueError(f"Unbalanced CREATE TABLE for {table}")

    body = sql[start + 1 : end]
    col_defs: list[str] = []
    # Split on commas not inside parentheses
    parts: list[str] = []
    buf = []
    depth = 0
    for ch in body:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())

    for part in parts:
        upper = part.upper().strip()
        if upper.startswith("PRIMARY KEY"):
            col_defs.append(part)
            continue
        if upper.startswith("UNIQUE KEY") or upper.startswith("UNIQUE INDEX"):
            # UNIQUE KEY `name` (`col`)
            um = re.search(r"`?(\w+)`?\s*\((.+)\)", part)
            if um:
                idx_name = um.group(1)
                cols = um.group(2)
                index_statements.append(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS `{idx_name}` ON `{table}` ({cols})"
                )
            continue
        if upper.startswith("KEY ") or upper.startswith("INDEX "):
            km = re.search(r"`?(\w+)`?\s*\((.+)\)", part)
            if km:
                idx_name = km.group(1)
                cols = km.group(2)
                index_statements.append(
                    f"CREATE INDEX IF NOT EXISTS `{idx_name}` ON `{table}` ({cols})"
                )
            continue
        if upper.startswith("CONSTRAINT") or upper.startswith("FOREIGN KEY"):
            # Drop FKs for SQLite import; data is preserved as-is
            continue

        # Column definition — normalize types
        col = part
        col = re.sub(r"\bint\(\d+\)", "INTEGER", col, flags=re.IGNORECASE)
        col = re.sub(r"\btinyint\(\d+\)", "INTEGER", col, flags=re.IGNORECASE)
        col = re.sub(r"\bbigint\(\d+\)", "INTEGER", col, flags=re.IGNORECASE)
        col = re.sub(r"\bvarchar\(\d+\)", "TEXT", col, flags=re.IGNORECASE)
        col = re.sub(r"\bchar\(\d+\)", "TEXT", col, flags=re.IGNORECASE)
        col = re.sub(r"\btext\b", "TEXT", col, flags=re.IGNORECASE)
        col = re.sub(r"\bdatetime\b", "DATETIME", col, flags=re.IGNORECASE)
        col = re.sub(r"\bdate\b", "DATE", col, flags=re.IGNORECASE)
        col = re.sub(r"\bfloat\b", "REAL", col, flags=re.IGNORECASE)
        col = re.sub(r"\bdouble\b", "REAL", col, flags=re.IGNORECASE)
        col = re.sub(r"\bAUTO_INCREMENT\b", "", col, flags=re.IGNORECASE)
        col = re.sub(r"\bCOLLATE\s+\w+", "", col, flags=re.IGNORECASE)
        col = re.sub(r"\s+", " ", col).strip()
        # Prefer INTEGER PRIMARY KEY for autoincrement id columns
        if re.match(r"`?id`?\s+INTEGER\s+NOT NULL", col, re.IGNORECASE):
            col = "`id` INTEGER NOT NULL"
        col_defs.append(col)

    create = f"CREATE TABLE `{table}` (\n  " + ",\n  ".join(col_defs) + "\n)"
    return create, index_statements


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split dump into statements, respecting quotes and comments."""
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    in_backtick = False
    i = 0
    length = len(sql_text)
    while i < length:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < length else ""

        # Line comment
        if not in_single and not in_double and not in_backtick and ch == "-" and nxt == "-":
            while i < length and sql_text[i] != "\n":
                i += 1
            continue

        if ch == "'" and not in_double and not in_backtick:
            # handle escaped ''
            if in_single and nxt == "'":
                buf.append("''")
                i += 2
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


def import_mysql_dump_to_sqlite(
    dump_path: Path | str,
    sqlite_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Import a full MySQL .sql backup into SQLite with ZERO row skipping.
    Schema + data come from the dump file exactly (all columns, all rows).
    """
    import re
    import sqlite3

    dump_path = Path(dump_path)
    if not dump_path.exists():
        return {"success": False, "message": f"Dump file not found: {dump_path}"}

    ensure_data_dir()
    db_path = Path(sqlite_path) if sqlite_path else (DATA_DIR / "mygym_local.db")
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-journal", "-wal", "-shm"):
        extra = Path(str(db_path) + suffix)
        if extra.exists():
            extra.unlink()

    sql_text = dump_path.read_text(encoding="utf-8", errors="replace")
    statements = _split_sql_statements(sql_text)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA journal_mode=OFF")
    counts: dict[str, int] = {}
    tables_created = 0
    inserts_run = 0

    try:
        for stmt in statements:
            upper = stmt.lstrip().upper()
            if upper.startswith("SET ") or upper.startswith("LOCK ") or upper.startswith("UNLOCK "):
                continue
            if upper.startswith("USE "):
                continue

            if upper.startswith("DROP TABLE"):
                # Normalize to SQLite
                drop = re.sub(
                    r"DROP TABLE IF EXISTS\s+`?(\w+)`?",
                    r"DROP TABLE IF EXISTS `\1`",
                    stmt,
                    flags=re.IGNORECASE,
                )
                conn.execute(drop)
                continue

            if upper.startswith("CREATE TABLE"):
                create_sql, indexes = _mysql_create_to_sqlite(stmt)
                conn.execute(create_sql)
                for idx in indexes:
                    try:
                        conn.execute(idx)
                    except sqlite3.Error as exc:
                        logger.warning("Index create skipped (%s): %s", exc, idx)
                tables_created += 1
                continue

            if upper.startswith("INSERT INTO"):
                # SQLite accepts backticks; MySQL INSERT multi-values works in SQLite
                insert_sql = stmt
                # COUNT rows roughly: number of value tuples
                table_m = re.search(r"INSERT INTO\s+`?(\w+)`?", insert_sql, re.IGNORECASE)
                table_name = table_m.group(1) if table_m else "unknown"
                # Execute — never skip
                conn.execute(insert_sql)
                # Count rows inserted: use changes() for last statement
                n = conn.total_changes  # cumulative; compute delta below
                inserts_run += 1
                # Better row count: count top-level value groups is hard; use SELECT after
                counts[table_name] = counts.get(table_name, 0)  # filled after loop
                continue

        # Fill accurate counts
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        for (name,) in cur.fetchall():
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM `{name}`").fetchone()[0]

        conn.commit()
        total = sum(counts.values())
        message = (
            f"Imported ALL data from {dump_path.name}: "
            f"{tables_created} tables, {total} rows (nothing skipped)."
        )
        meta = load_sync_meta()
        now = utc_now_iso()
        meta.update(
            {
                "last_seed_at": now,
                "last_seed_status": "success",
                "last_seed_source": str(dump_path),
                "last_seed_counts": counts,
                "last_seed_message": message,
                "last_push_at": meta.get("last_push_at") or now,
                "last_push_status": meta.get("last_push_status") or "synced_via_seed",
                "last_push_message": meta.get("last_push_message")
                or "Local SQLite loaded from full SQL dump; waiting for next backup window.",
            }
        )
        save_sync_meta(meta)
        logger.info(message)
        return {
            "success": True,
            "skipped": False,
            "message": message,
            "counts": counts,
            "source": str(dump_path),
        }
    except Exception as exc:
        conn.rollback()
        logger.exception("import_mysql_dump_to_sqlite failed")
        meta = load_sync_meta()
        meta.update(
            {
                "last_seed_at": utc_now_iso(),
                "last_seed_status": "error",
                "last_seed_message": str(exc),
            }
        )
        save_sync_meta(meta)
        return {"success": False, "skipped": False, "message": str(exc)}
    finally:
        conn.close()


def resolve_seed_dump() -> Path | None:
    """Prefer configured dump, then the known full backup, then latest .sql in backups/."""
    configured = os.getenv("SQLITE_SEED_DUMP", "").strip()
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = SCRIPT_DIR / p
        if p.exists():
            return p
    if DEFAULT_SEED_DUMP.exists():
        return DEFAULT_SEED_DUMP
    if BACKUP_DIR.exists():
        dumps = sorted(BACKUP_DIR.glob("*.sql"), key=lambda x: x.stat().st_mtime, reverse=True)
        if dumps:
            return dumps[0]
    return None


def _copy_tables(src_engine: Engine, dst_engine: Engine, table_names: list[str]) -> dict[str, int]:
    """Full replace: wipe destination tables then copy ALL rows from source (no skipping)."""
    src_meta = MetaData()
    dst_meta = MetaData()
    src_meta.reflect(bind=src_engine, only=table_names)
    dst_meta.reflect(bind=dst_engine, only=table_names)

    counts: dict[str, int] = {}
    dialect = dst_engine.dialect.name

    with dst_engine.begin() as dst_conn:
        _disable_fk(dst_conn, dialect)

        for name in reversed(table_names):
            if name not in dst_meta.tables:
                continue
            dst_conn.execute(dst_meta.tables[name].delete())

        with src_engine.connect() as src_conn:
            for name in table_names:
                if name not in src_meta.tables or name not in dst_meta.tables:
                    counts[name] = 0
                    continue

                src_table = src_meta.tables[name]
                dst_table = dst_meta.tables[name]
                # Prefer destination columns that also exist on source; include every
                # shared column so no field present on both sides is dropped.
                common_cols = [
                    c for c in src_table.columns.keys() if c in dst_table.columns.keys()
                ]
                if not common_cols:
                    counts[name] = 0
                    continue

                rows = src_conn.execute(select(src_table)).mappings().all()
                inserted = 0
                for row in rows:
                    item = {col: row[col] for col in common_cols}
                    dst_conn.execute(dst_table.insert().values(**item))
                    inserted += 1
                counts[name] = inserted
                logger.info("Synced table %s: %s rows (all rows)", name, inserted)

        _enable_fk(dst_conn, dialect)

    return counts


def seed_sqlite_from_dump(
    sqlite_path: Path | str | None = None,
    force: bool = False,
    dump_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Load ALL data into local SQLite from a local .sql dump file only.
    Never connects to live MySQL.
    """
    ensure_data_dir()
    db_path = Path(sqlite_path) if sqlite_path else (DATA_DIR / "mygym_local.db")
    sqlite_engine = get_engine(sqlite_uri(db_path))

    try:
        if not force and not local_db_is_empty(sqlite_engine):
            return {
                "success": True,
                "skipped": True,
                "message": "Local SQLite already has data; seed skipped.",
            }
    finally:
        sqlite_engine.dispose()

    dump = Path(dump_path) if dump_path else resolve_seed_dump()
    if not dump or not dump.exists():
        return {
            "success": False,
            "skipped": False,
            "message": "No local SQL dump found to seed SQLite. Place a backup in backups/.",
        }

    return import_mysql_dump_to_sqlite(dump, db_path)


# Backwards-compatible alias (dump-only; does not touch live MySQL)
def seed_sqlite_from_mysql(
    sqlite_path: Path | str | None = None,
    mysql_uri: str | None = None,
    force: bool = False,
    dump_path: Path | str | None = None,
) -> dict[str, Any]:
    """Deprecated name — seeds from local dump only, never live MySQL."""
    return seed_sqlite_from_dump(
        sqlite_path=sqlite_path,
        force=force,
        dump_path=dump_path,
    )


def push_sqlite_to_mysql(
    sqlite_path: Path | str | None = None,
    mysql_uri: str | None = None,
) -> dict[str, Any]:
    """Push all local SQLite data to MySQL (full replace of synced tables)."""
    ensure_data_dir()
    sqlite_engine = get_engine(sqlite_uri(sqlite_path))
    mysql_engine = get_engine(mysql_uri or mysql_uri_from_env())

    try:
        tables = _table_names_present(sqlite_engine, TABLE_ORDER)
        if not tables:
            return {
                "success": False,
                "message": "No local tables found to push.",
            }

        mysql_meta = MetaData()
        mysql_meta.reflect(bind=mysql_engine)
        missing = [t for t in tables if t not in mysql_meta.tables]
        if missing:
            return {
                "success": False,
                "message": f"MySQL missing tables: {', '.join(missing)}.",
            }

        counts = _copy_tables(sqlite_engine, mysql_engine, tables)
        total = sum(counts.values())
        message = f"Pushed {total} rows to live MySQL ({len(tables)} tables)."
        meta = load_sync_meta()
        meta.update(
            {
                "last_push_at": utc_now_iso(),
                "last_push_status": "success",
                "last_push_counts": counts,
                "last_push_message": message,
                "last_push_mode": "manual_or_auto",
            }
        )
        save_sync_meta(meta)
        return {"success": True, "message": message, "counts": counts}
    except Exception as exc:
        meta = load_sync_meta()
        meta.update(
            {
                "last_push_at": utc_now_iso(),
                "last_push_status": "error",
                "last_push_message": str(exc),
            }
        )
        save_sync_meta(meta)
        logger.exception("push_sqlite_to_mysql failed")
        return {"success": False, "message": str(exc)}
    finally:
        sqlite_engine.dispose()
        mysql_engine.dispose()


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    if type(value).__name__ == "date":
        return f"'{value.isoformat()}'"
    if type(value).__name__ == "time":
        return f"'{value.isoformat()}'"
    if isinstance(value, (bytes, bytearray, memoryview)):
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


def export_sqlite_local_backup(
    sqlite_path: Path | str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """
    Save a full local .sql dump of SQLite into backups/, plus a .db copy.
    Does not connect to MySQL.
    """
    import shutil
    import sqlite3

    ensure_data_dir()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    db_path = Path(sqlite_path) if sqlite_path else (DATA_DIR / "mygym_local.db")
    if not db_path.exists():
        return {"success": False, "message": f"SQLite file not found: {db_path}"}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    sql_out = BACKUP_DIR / f"alphafitness_{stamp}{suffix}.sql"
    db_out = BACKUP_DIR / f"alphafitness_{stamp}{suffix}.db"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        if not tables:
            return {"success": False, "message": "No tables found in local SQLite."}

        total_rows = 0
        with sql_out.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("-- Alpha Fitness Gym DB Backup (from local SQLite)\n")
            fh.write(f"-- Created: {datetime.now().isoformat(timespec='seconds')}\n")
            fh.write(f"-- Source: {db_path.name}\n")
            fh.write("SET NAMES utf8mb4;\n")
            fh.write("SET FOREIGN_KEY_CHECKS=0;\n")
            fh.write("SET UNIQUE_CHECKS=0;\n")
            fh.write("SET SQL_MODE='NO_AUTO_VALUE_ON_ZERO';\n\n")

            for table in tables:
                # Prefer original CREATE if we can rebuild a simple MySQL-ish dump
                row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                create_sql = row[0] if row and row[0] else f"CREATE TABLE `{table}` (id INTEGER PRIMARY KEY)"

                fh.write("-- ----------------------------\n")
                fh.write(f"-- Table structure for {table}\n")
                fh.write("-- ----------------------------\n")
                fh.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                fh.write(f"{create_sql};\n\n")

                col_info = conn.execute(f"PRAGMA table_info(`{table}`)").fetchall()
                col_names = [c[1] for c in col_info]
                rows = conn.execute(f"SELECT * FROM `{table}`").fetchall()
                if not rows:
                    fh.write(f"-- No data in {table}\n\n")
                    continue

                fh.write("-- ----------------------------\n")
                fh.write(f"-- Data for {table} ({len(rows)} rows)\n")
                fh.write("-- ----------------------------\n")
                cols_sql = ", ".join(f"`{c}`" for c in col_names)
                fh.write(f"INSERT INTO `{table}` ({cols_sql}) VALUES\n")
                value_lines = []
                for row in rows:
                    vals = ", ".join(_sql_literal(row[c]) for c in col_names)
                    value_lines.append(f"({vals})")
                fh.write(",\n".join(value_lines))
                fh.write(";\n\n")
                total_rows += len(rows)

            fh.write("SET FOREIGN_KEY_CHECKS=1;\n")
            fh.write("SET UNIQUE_CHECKS=1;\n")
            fh.write("-- Backup complete\n")

        # Also keep a raw SQLite file copy for easy restore
        shutil.copy2(db_path, db_out)

        meta = load_sync_meta()
        meta.update(
            {
                "last_local_backup_at": utc_now_iso(),
                "last_local_backup_sql": str(sql_out.name),
                "last_local_backup_db": str(db_out.name),
                "last_local_backup_rows": total_rows,
                "last_local_backup_status": "success",
            }
        )
        save_sync_meta(meta)

        message = (
            f"Local backup saved: {sql_out.name} and {db_out.name} "
            f"({len(tables)} tables, {total_rows} rows)."
        )
        return {
            "success": True,
            "message": message,
            "sql_file": str(sql_out),
            "db_file": str(db_out),
            "tables": len(tables),
            "rows": total_rows,
        }
    except Exception as exc:
        meta = load_sync_meta()
        meta.update(
            {
                "last_local_backup_at": utc_now_iso(),
                "last_local_backup_status": "error",
                "last_local_backup_message": str(exc),
            }
        )
        save_sync_meta(meta)
        logger.exception("export_sqlite_local_backup failed")
        return {"success": False, "message": str(exc)}
    finally:
        conn.close()


def run_full_backup(
    sqlite_path: Path | str | None = None,
    mysql_uri: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """
    Backup now:
      1) Save local .sql + .db under backups/
      2) Push SQLite data to live MySQL
    """
    local = export_sqlite_local_backup(sqlite_path=sqlite_path, label=label)
    if not local.get("success"):
        return {
            "success": False,
            "message": f"Local backup failed: {local.get('message')}",
            "local": local,
            "mysql": None,
        }

    online = push_sqlite_to_mysql(sqlite_path=sqlite_path, mysql_uri=mysql_uri)
    success = bool(online.get("success"))
    if success:
        message = f"{local.get('message')} {online.get('message')}"
    else:
        message = (
            f"{local.get('message')} MySQL push failed: {online.get('message')}"
        )

    meta = load_sync_meta()
    meta["last_full_backup_at"] = utc_now_iso()
    meta["last_full_backup_status"] = "success" if success else "partial"
    meta["last_full_backup_message"] = message
    save_sync_meta(meta)

    return {
        "success": success,
        "message": message,
        "local": local,
        "mysql": online,
    }


def list_recent_local_backups(limit: int = 10) -> list[dict[str, Any]]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        list(BACKUP_DIR.glob("alphafitness_*.sql")) + list(BACKUP_DIR.glob("alphafitness_*.db")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out = []
    for p in files[:limit]:
        out.append(
            {
                "name": p.name,
                "path": str(p),
                "size_kb": round(p.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return out


def sync_status_summary(sqlite_path: Path | str | None = None) -> dict[str, Any]:
    meta = load_sync_meta()
    elapsed = hours_since_last_push()
    local_counts: dict[str, int] = {}
    try:
        engine = get_engine(sqlite_uri(sqlite_path))
        for name in _table_names_present(engine, TABLE_ORDER):
            try:
                local_counts[name] = count_rows(engine, name)
            except Exception:
                local_counts[name] = -1
        engine.dispose()
    except Exception as exc:
        local_counts = {"error": str(exc)}  # type: ignore[dict-item]

    return {
        "meta": meta,
        "hours_since_last_push": round(elapsed, 2) if elapsed is not None else None,
        "due_for_auto_push": should_auto_push(
            float(os.getenv("BACKUP_AUTO_PUSH_HOURS", "24"))
        ),
        "local_counts": local_counts,
        "sqlite_path": str((Path(sqlite_path) if sqlite_path else DATA_DIR / "mygym_local.db").resolve()),
        "recent_backups": list_recent_local_backups(8),
    }
