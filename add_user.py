from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash
from urllib.parse import quote_plus

# ---- CONFIG ----
DB_USER = "mygymlahore_Waheedadmin"
DB_PASS = "Waheed@shapeitup"
DB_HOST = "148.163.100.132"
DB_PORT = 3306
DB_NAME = "mygymlahore_mygymbarkatmarket"

USERNAME = "WaheedKhanMyGYM"
PASSWORD = "Waheed@shapeitup"
ROLE_ID = 1

# URL-encode password
DB_PASS_URL = quote_plus(DB_PASS)

# SQLAlchemy connection string
connection_string = f"mysql+pymysql://{DB_USER}:{DB_PASS_URL}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Hash the password
hashed_password = generate_password_hash(PASSWORD)

# SQL query
SQL = text("""
    INSERT INTO user (username, password_hash, role_id, created_at, updated_at)
    VALUES (:username, :password_hash, :role_id, NOW(), NOW())
""")

try:
    engine = create_engine(connection_string)
    with engine.begin() as conn:
        result = conn.execute(SQL, {
            'username': USERNAME,
            'password_hash': hashed_password,
            'role_id': str(ROLE_ID)
        })
        print("User inserted successfully!")
except Exception as e:
    print("Error occurred:", e)
