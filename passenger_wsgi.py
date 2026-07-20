import os

# cPanel / hosted site uses live MySQL. Desktop app uses SQLite separately.
os.environ["DB_BACKEND"] = "mysql"

from app import app as application
