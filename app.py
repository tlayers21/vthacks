import sqlite3

# Example of connecting to database
conn = sqlite3.connect("app.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM users;")
results = cursor.fetchall()
print(results)
