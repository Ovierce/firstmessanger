import eventlet
eventlet.monkey_patch()  # СТРОГО ПЕРВАЯ СТРОКА для исправления ошибки "not greened"

import os
import sqlite3
from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash # Для регистрации

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-2026'
# Исправление ошибки "Request Entity Too Large" (лимит 16МБ)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

# Настройка сокетов с поддержкой eventlet и большими буферами
socketio = SocketIO(app, 
    cors_allowed_origins="*", 
    max_http_buffer_size=16 * 1024 * 1024,
    async_mode='eventlet'
)

DATABASE = 'chat.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Функция создания таблиц (решает ошибку "no such table: users")
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    # Принудительное создание таблиц при каждом подключении (для страховки)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    return conn
    
@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session['user'])

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form.get('username').strip()
        p = request.form.get('password')
        if not u or not p:
            flash("Заполните все поля")
            return redirect(url_for('register'))
        
        hashed_p = generate_password_hash(p)
        try:
            with get_db() as conn:
                conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, hashed_p))
                conn.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Никнейм занят") #
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username = ?', (u,)).fetchone()
            if user and check_password_hash(user['password'], p):
                session['user'] = u
                return redirect(url_for('index'))
        flash("Неверный логин или пароль")
    return render_template('login.html')

@socketio.on('send_message')
def handle_message(data):
    msg = data.get('message')
    user = session.get('user', 'Guest')
    if msg:
        with get_db() as conn:
            conn.execute('INSERT INTO messages (username, message) VALUES (?, ?)', (user, msg))
            conn.commit()
        emit('receive_message', {'username': user, 'message': msg}, broadcast=True)

if __name__ == '__main__':
    init_db() # Создаем таблицы ПЕРЕД запуском
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)







