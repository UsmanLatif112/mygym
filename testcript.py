import os
import time
from datetime import datetime
from dotenv import load_dotenv
from zk import ZK

load_dotenv()

ZK_IP = os.getenv("ZK_IP", "")
ZK_PORT = int(os.getenv("ZK_PORT", "4370"))
ZK_TIMEOUT = int(os.getenv("ZK_TIMEOUT", "10"))
ZK_PASSWORD = int(os.getenv("ZK_PASSWORD", "0"))

TEST_USER_ID = datetime.now().strftime("%H%M%S")[-5:]
TEST_NAME = "ENROLL TEST"
TEMP_ID = 0


def log(*parts):
    print(f"[{datetime.now().strftime('%H:%M:%S')}]", *parts)


def connect_device():
    if not ZK_IP:
        raise Exception("ZK_IP missing in .env")

    zk = ZK(
        ZK_IP,
        port=ZK_PORT,
        timeout=ZK_TIMEOUT,
        password=ZK_PASSWORD,
        force_udp=False,
        ommit_ping=False,
    )
    return zk.connect()


def find_user(conn, user_id):
    users = conn.get_users() or []
    for u in users:
        if str(getattr(u, "user_id", "")).strip() == str(user_id).strip():
            return u
    return None


def get_next_uid(conn):
    users = conn.get_users() or []
    used_uids = {
        getattr(u, "uid", None)
        for u in users
        if getattr(u, "uid", None) is not None
    }
    uid = 1
    while uid in used_uids:
        uid += 1
    return uid


def ensure_user_exists(conn, user_id, name):
    user = find_user(conn, user_id)
    if user:
        log("User already exists:", {
            "uid": getattr(user, "uid", None),
            "user_id": getattr(user, "user_id", None),
            "name": getattr(user, "name", None),
        })
        return user

    uid = get_next_uid(conn)
    log(f"Creating user uid={uid}, user_id={user_id}, name={name}")
    conn.set_user(
        uid=uid,
        name=(name or f"User {user_id}")[:24],
        privilege=0,
        password="",
        group_id="",
        user_id=str(user_id),
    )

    time.sleep(1)

    user = find_user(conn, user_id)
    if not user:
        raise Exception("User creation command sent but user was not found afterward")

    log("User created:", {
        "uid": getattr(user, "uid", None),
        "user_id": getattr(user, "user_id", None),
        "name": getattr(user, "name", None),
    })
    return user


def start_enrollment(conn, uid, user_id, temp_id=0):
    log(f"Calling enroll_user(uid={uid}, temp_id={temp_id}, user_id={user_id})")
    try:
        result = conn.enroll_user(uid=uid, temp_id=temp_id, user_id=str(user_id))
        log("enroll_user returned:", result)
        return {
            "success": True,
            "result": result,
            "message": "Enrollment command sent to machine."
        }
    except Exception as exc:
        log("enroll_user exception:", repr(exc))
        return {
            "success": True,
            "result": repr(exc),
            "message": "Enrollment command likely sent; device behavior should be checked visually."
        }


def main():
    conn = None
    try:
        log(f"Connecting to {ZK_IP}:{ZK_PORT}")
        conn = connect_device()
        conn.disable_device()

        log("Connected")
        log("Device:", conn.get_device_name())
        log("Firmware:", conn.get_firmware_version())
        log("Serial:", conn.get_serialnumber())

        user = ensure_user_exists(conn, TEST_USER_ID, TEST_NAME)
        uid = getattr(user, "uid", None)
        if uid is None:
            raise Exception("Could not determine uid for user")

        result = start_enrollment(conn, uid, TEST_USER_ID, TEMP_ID)

        log(result["message"])
        log("If the machine is prompting, place finger now.")

        for i in range(15, 0, -1):
            print(f"Waiting for device interaction... {i}s", end="\r")
            time.sleep(1)
        print()

        log("Test completed.")

    except Exception as exc:
        log("ERROR:", repr(exc))
    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
        log("Disconnected")


if __name__ == "__main__":
    main()
