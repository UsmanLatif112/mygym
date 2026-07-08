"""Fetch attendance logs from a ZKTeco device using pyzk."""

from attendance_utils import parse_check_in_at


def attendance_record_to_event(record, device_sn=None):
    """Map a pyzk attendance record to app ingest event format."""
    user_id = getattr(record, "user_id", None)
    timestamp = getattr(record, "timestamp", None)
    uid = getattr(record, "uid", None)

    if user_id is None or timestamp is None:
        return None

    thumb_id = str(user_id).strip()
    check_in_at = parse_check_in_at(timestamp)
    if not thumb_id or not check_in_at:
        return None

    event_id = f"zk_{thumb_id}_{check_in_at.strftime('%Y%m%d%H%M%S')}"
    return {
        "thumb_id": thumb_id,
        "check_in_at": check_in_at.isoformat(),
        "source": "zkteco_device",
        "device_sn": device_sn,
        "raw_uid": str(uid) if uid is not None else None,
        "event_id": event_id,
    }


def fetch_zkteco_attendance_events(ip, port=4370, timeout=10, password=0):
    """
    Connect to ZKTeco machine and return attendance events for app ingestion.

    Field mapping from device -> app:
      user_id   -> thumb_id   (must match customer.thumb_id)
      timestamp -> check_in_at
      uid       -> raw_uid
    """
    from zk import ZK

    zk = ZK(
        ip,
        port=port,
        timeout=timeout,
        password=password,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None
    try:
        conn = zk.connect()
        conn.disable_device()

        device_sn = None
        try:
            device_sn = conn.get_serialnumber()
        except Exception:
            pass

        attendance_logs = conn.get_attendance() or []
        events = []
        for record in attendance_logs:
            event = attendance_record_to_event(record, device_sn=device_sn)
            if event:
                events.append(event)
        return events
    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
