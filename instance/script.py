from zk import ZK

zk = ZK(
    ip='192.168.1.201',
    port=4370,
    timeout=5,
    password=0  # Comm Key
)

conn = zk.connect()

users = conn.get_users()
attendance = conn.get_attendance()

print(users)
print(attendance)

conn.disconnect()