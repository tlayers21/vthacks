import sqlite3
from db.init_db import DB_PATH

# Example of connecting to database
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT name FROM customers;")
results = cursor.fetchall()
print(results)
