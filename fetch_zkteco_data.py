"""
Fetch all users + attendance logs from a ZKTeco machine using pyzk.

Install:
    pip install pyzk

Run:
    python fetch_zkteco_data.py
"""

import json
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

ZK_IP = os.getenv("ZK_IP", "")
ZK_PORT = int(os.getenv("ZK_PORT", "4370"))
ZK_TIMEOUT = int(os.getenv("ZK_TIMEOUT", "10"))
ZK_PASSWORD = int(os.getenv("ZK_PASSWORD", "0"))
OUTPUT_PREFIX = os.getenv("OUTPUT_PREFIX", "zkteco_export")


def user_to_dict(user):
    return {
        "uid": getattr(user, "uid", None),
        "user_id": getattr(user, "user_id", None),
        "name": getattr(user, "name", None),
        "privilege": getattr(user, "privilege", None),
        "password": getattr(user, "password", None),
        "group_id": getattr(user, "group_id", None),
        "card": getattr(user, "card", None),
    }


def main():
    if not ZK_IP:
        print("Error: ZK_IP is not set. Add it to your .env file.")
        return

    from zk import ZK

    zk = ZK(
        ZK_IP,
        port=ZK_PORT,
        timeout=ZK_TIMEOUT,
        password=ZK_PASSWORD,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None
    try:
        print(f"Connecting to ZKTeco at {ZK_IP}:{ZK_PORT} ...")
        conn = zk.connect()
        conn.disable_device()

        serial = conn.get_serialnumber()
        device_name = conn.get_device_name()
        firmware = conn.get_firmware_version()
        print("Connected.")
        print("Serial:", serial)
        print("Device:", device_name)
        print("Firmware:", firmware)

        users = conn.get_users() or []
        users_data = [user_to_dict(user) for user in users]
        print(f"Fetched users: {len(users_data)}")

        attendance_logs = conn.get_attendance() or []
        attendance_data = [
            {
                "uid": getattr(record, "uid", None),
                "user_id": getattr(record, "user_id", None),
                "timestamp": str(getattr(record, "timestamp", None)),
                "status": getattr(record, "status", None),
                "punch": getattr(record, "punch", None),
            }
            for record in attendance_logs
        ]
        print(f"Fetched attendance logs: {len(attendance_data)}")

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        users_file = f"{OUTPUT_PREFIX}_users_{now}.json"
        attendance_file = f"{OUTPUT_PREFIX}_attendance_{now}.json"

        with open(users_file, "w", encoding="utf-8") as file:
            json.dump(users_data, file, indent=2, ensure_ascii=False)

        with open(attendance_file, "w", encoding="utf-8") as file:
            json.dump(attendance_data, file, indent=2, ensure_ascii=False)

        print(f"Saved: {users_file}")
        print(f"Saved: {attendance_file}")
    except Exception as exc:
        print("Error:", str(exc))
    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
        print("Done.")


if __name__ == "__main__":
    main()
