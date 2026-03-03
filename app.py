import eventlet
eventlet.monkey_patch()

import os
import sqlite3
from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-key-777'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)

DATABASE = 'chat.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Пользователи: добавляем тему и аватарку
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, 
             avatar TEXT DEFAULT '1', theme TEXT DEFAULT 'light')''')
        # Сообщения: добавляем получателя (recipient). Если NULL — это общий чат.
        conn.execute('''CREATE TABLE IF NOT EXISTS messages 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, recipient TEXT, 
             message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

init_db()

@app.route('/')
def index():
    if 'user' not in session: return redirect(url_for('login'))
    with get_db() as conn:
        me = conn.execute('SELECT * FROM users WHERE username = ?', (session['user'],)).fetchone()
        all_users = conn.execute('SELECT username, avatar FROM users WHERE username != ?', (session['user'],)).fetchall()
        # История общего чата
        messages = conn.execute('SELECT * FROM messages WHERE recipient IS NULL ORDER BY timestamp ASC').fetchall()
    return render_template('index.html', username=session['user'], me=me, users=all_users, messages=messages)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u, p = request.form.get('username').strip(), request.form.get('password')
        try:
            with get_db() as conn:
                conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, generate_password_hash(p)))
                conn.commit()
            return redirect(url_for('login'))
        except: flash("Ошибка или ник занят")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form.get('username'), request.form.get('password')
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username = ?', (u,)).fetchone()
            if user and check_password_hash(user['password'], p):
                session['user'] = u
                return redirect(url_for('index'))
        flash("Неверные данные")
    return render_template('login.html')

@app.route('/update_settings', methods=['POST'])
def update_settings():
    if 'user' not in session: return "Error", 403
    theme = request.form.get('theme')
    avatar = request.form.get('avatar')
    with get_db() as conn:
        conn.execute('UPDATE users SET theme = ?, avatar = ? WHERE username = ?', (theme, avatar, session['user']))
        conn.commit()
    return redirect(url_for('index'))

# Сокеты
@socketio.on('send_msg')
def handle_msg(data):
    sender = session.get('user')
    msg = data.get('message')
    recipient = data.get('recipient') # Если есть — это ЛС
    
    with get_db() as conn:
        conn.execute('INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)', (sender, recipient, msg))
        conn.commit()
    
    output = {'sender': sender, 'message': msg, 'recipient': recipient}
    if recipient:
        emit('receive_msg', output, room=recipient)
        emit('receive_msg', output, room=sender)
    else:
        emit('receive_msg', output, broadcast=True)

@socketio.on('join')
def on_join(data):
    join_room(session.get('user'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))


