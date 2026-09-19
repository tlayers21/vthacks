from flask import Flask, render_template
import sqlite3
from db.init_db import DB_PATH

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
