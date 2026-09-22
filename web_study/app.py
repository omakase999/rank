from flask import Flask, jsonify, request, send_from_directory
import sqlite3
import os

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'todos.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/style.css')
def style():
    return send_from_directory(BASE_DIR, 'style.css')


@app.route('/script.js')
def script():
    return send_from_directory(BASE_DIR, 'script.js')


@app.route('/api/todos', methods=['GET'])
def get_todos():
    conn = get_db()
    rows = conn.execute('SELECT id, content FROM todos').fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/todos', methods=['POST'])
def add_todo():
    content = request.get_json()['content']
    conn = get_db()
    conn.execute('INSERT INTO todos (content) VALUES (?)', (content,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
