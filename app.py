import eventlet
eventlet.monkey_patch()

import os
import sqlite3
from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "tg-clone-secret-key")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
DATABASE = 'chat.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Добавили bio (о себе)
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, 
             avatar TEXT DEFAULT '👤', bio TEXT DEFAULT '', theme TEXT DEFAULT 'light')''')
        # recipient: если NULL - общий чат, если текст - ник получателя (ЛС)
        conn.execute('''CREATE TABLE IF NOT EXISTS messages 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, recipient TEXT, 
             message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

init_db()

@app.route('/')
def index():
    if 'user' not in session: return redirect(url_for('login'))
    
    current_chat = request.args.get('chat') # Узнаем, какой чат открыт
    
    with get_db() as conn:
        me = conn.execute('SELECT * FROM users WHERE username = ?', (session['user'],)).fetchone()
        if not me:
            session.pop('user', None)
            return redirect(url_for('login'))
            
        users = conn.execute('SELECT username, avatar, bio FROM users WHERE username != ?', (session['user'],)).fetchall()
        
        # Загрузка сообщений в зависимости от выбранного чата
        if current_chat:
            messages = conn.execute('''
                SELECT * FROM messages 
                WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?) 
                ORDER BY timestamp ASC
            ''', (session['user'], current_chat, current_chat, session['user'])).fetchall()
            chat_info = conn.execute('SELECT username, avatar FROM users WHERE username = ?', (current_chat,)).fetchone()
            curr_group = {'id': current_chat, 'name': current_chat, 'type': 'dm', 'avatar': chat_info['avatar'] if chat_info else '👤'}
        else:
            messages = conn.execute('SELECT * FROM messages WHERE recipient IS NULL ORDER BY timestamp ASC').fetchall()
            curr_group = {'id': 'global', 'name': 'Общий чат', 'type': 'global', 'avatar': '🌍'}
            
    return render_template('index.html', me=me, users=users, messages=messages, curr_group=curr_group)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user' not in session: return redirect(url_for('login'))
    avatar = request.form.get('avatar', '👤')
    bio = request.form.get('bio', '')
    theme = request.form.get('theme', 'light')
    
    with get_db() as conn:
        conn.execute('UPDATE users SET avatar = ?, bio = ?, theme = ? WHERE username = ?', 
                     (avatar, bio, theme, session['user']))
        conn.commit()
    return redirect(url_for('index', chat=request.args.get('chat')))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form.get('username').strip()
        p = request.form.get('password')
        try:
            with get_db() as conn:
                conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, generate_password_hash(p)))
                conn.commit()
            return redirect(url_for('login'))
        except: flash("Никнейм уже занят")
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

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect():
    if 'user' in session:
        join_room(session['user']) # Пользователь заходит в свою "комнату" для ЛС

@socketio.on('send_msg')
def handle_msg(data):
    sender = session.get('user')
    if not sender: return
    
    msg = data.get('message')
    recipient = data.get('recipient') # 'global' или 'Username'
    
    db_recipient = None if recipient == 'global' else recipient
    
    with get_db() as conn:
        conn.execute('INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)', (sender, db_recipient, msg))
        conn.commit()
    
    # Отправляем сообщение
    out_data = {'sender': sender, 'message': msg, 'recipient': recipient}
    
    if db_recipient:
        emit('receive_msg', out_data, room=db_recipient)
        emit('receive_msg', out_data, room=sender)
    else:
        emit('receive_msg', out_data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
