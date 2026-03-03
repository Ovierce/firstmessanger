import eventlet
eventlet.monkey_patch()  # СТРОГО ПЕРВАЯ СТРОКА!

import os
import sqlite3
from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-2026'

# РЕШЕНИЕ ОШИБКИ "Request Entity Too Large"
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

# РЕШЕНИЕ ОШИБКИ "Internal Server Error" при работе с фото
socketio = SocketIO(app, 
    cors_allowed_origins="*", 
    max_http_buffer_size=16 * 1024 * 1024,
    async_mode='eventlet'
)

# ... далее идет твой остальной код (get_db, init_db и т.д.) ...

def get_db():
    conn = sqlite3.connect('chat.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, avatar TEXT, bio TEXT DEFAULT "Привет! Я использую Messenger")')
        c.execute('CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, is_private INTEGER DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER, username TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, username TEXT, content TEXT)')
        c.execute('INSERT OR IGNORE INTO groups (id, name, is_private) VALUES (1, "Общий чат", 0)')
        conn.commit()

@app.route('/')
def index():
    if 'username' in session: return redirect(url_for('chat', group_id=1))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form.get('username').strip(), request.form.get('password')
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username=?', (u,)).fetchone()
            if user and check_password_hash(user['password'], p):
                session['username'] = u
                return redirect(url_for('chat', group_id=1))
        flash('Неверные данные')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form.get('username').strip()
        p = generate_password_hash(request.form.get('password'))
        try:
            with get_db() as conn:
                conn.execute('INSERT INTO users (username, password) VALUES (?,?)', (u, p))
                conn.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Никнейм занят')
    return render_template('register.html')

@app.route('/chat/<int:group_id>')
def chat(group_id):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    with get_db() as conn:
        groups = conn.execute('''
            SELECT g.*, m.content as last_msg FROM groups g 
            LEFT JOIN group_members gm ON g.id = gm.group_id
            LEFT JOIN (SELECT group_id, content, MAX(id) FROM messages GROUP BY group_id) m ON g.id = m.group_id
            WHERE g.is_private = 0 OR gm.username = ? GROUP BY g.id
        ''', (me,)).fetchall()
        
        history = conn.execute('''
            SELECT m.*, u.avatar FROM messages m 
            JOIN users u ON m.username = u.username 
            WHERE m.group_id = ? ORDER BY m.id ASC
        ''', (group_id,)).fetchall()
        
        curr_g = conn.execute('SELECT * FROM groups WHERE id=?', (group_id,)).fetchone()
        my_data = conn.execute('SELECT * FROM users WHERE username=?', (me,)).fetchone()
    return render_template('index.html', me=my_data, groups=groups, history=history, curr_group=curr_g)

@app.route('/create-private/<target>')
def create_private(target):
    me = session['username']
    with get_db() as conn:
        exist = conn.execute('SELECT g.id FROM groups g JOIN group_members m1 ON g.id=m1.group_id JOIN group_members m2 ON g.id=m2.group_id WHERE g.is_private=1 AND m1.username=? AND m2.username=?', (me, target)).fetchone()
        if exist: return redirect(url_for('chat', group_id=exist['id']))
        c = conn.cursor()
        c.execute('INSERT INTO groups (name, is_private) VALUES (?, 1)', (f"{me} & {target}",))
        rid = c.lastrowid
        c.execute('INSERT INTO group_members VALUES (?, ?), (?, ?)', (rid, me, rid, target))
        conn.commit()
    return redirect(url_for('chat', group_id=rid))

@app.route('/edit-profile', methods=['POST'])
def edit_profile():
    with get_db() as conn:
        conn.execute('UPDATE users SET bio=?, avatar=? WHERE username=?', (request.form.get('bio'), request.form.get('avatar_data'), session['username']))
        conn.commit()
    return redirect(url_for('chat', group_id=1))

@socketio.on('join')
def on_join(data): join_room(str(data['room']))

@socketio.on('message')
def handle_msg(data):
    room, user, msg = str(data['room']), session['username'], data['msg']
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO messages (group_id, username, content) VALUES (?, ?, ?)', (room, user, msg))
        mid = c.lastrowid
        conn.commit()
        u = conn.execute('SELECT avatar FROM users WHERE username=?', (user,)).fetchone()
    emit('display_msg', {'id': mid, 'username': user, 'content': msg, 'avatar': u['avatar'], 'room_id': room}, room=room)

@socketio.on('delete_message')
def delete_msg(data):
    mid, user, room = data['id'], session['username'], str(data['room'])
    with get_db() as conn:
        res = conn.execute('SELECT username FROM messages WHERE id=?', (mid,)).fetchone()
        if res and res['username'] == user:
            conn.execute('DELETE FROM messages WHERE id=?', (mid,))
            conn.commit()
            emit('remove_msg', {'id': mid}, room=room)

@socketio.on('get_user_info')
def user_info(data):
    with get_db() as conn:
        u = conn.execute('SELECT username, avatar, bio FROM users WHERE username=?', (data['username'],)).fetchone()
    if u: emit('user_info_res', dict(u))

if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=5000)



