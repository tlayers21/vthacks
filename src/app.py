from flask import Flask, render_template
from db.connect import transaction, connect

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/finance")
def finance():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT c.name AS customer_name, c.role, d.name AS department_name "
        "FROM customers c JOIN departments d ON c.department_id = d.department_id;"
    )
    customers = cursor.fetchall()
    return render_template("finance.html", customers=customers)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
