import sqlite3

# Example of connecting to database
conn = sqlite3.connect("db/app.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM customers;")
results = cursor.fetchall()
print(results)
