import eventlet
eventlet.monkey_patch()

import os
import sqlite3
from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "tg-clone-secret-key")

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)
DATABASE = 'chat.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, 
             avatar TEXT DEFAULT '👤', bio TEXT DEFAULT '', theme TEXT DEFAULT 'light')''')
        conn.execute('''CREATE TABLE IF NOT EXISTS messages 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, recipient TEXT, 
             message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if 'user' not in session: return redirect(url_for('login'))
    current_chat = request.args.get('chat')
    with get_db() as conn:
        me = conn.execute('SELECT * FROM users WHERE username = ?', (session['user'],)).fetchone()
        if not me:
            session.pop('user', None)
            return redirect(url_for('login'))
        users = conn.execute('SELECT username, avatar, bio FROM users WHERE username != ?', (session['user'],)).fetchall()
        
        if current_chat:
            messages = conn.execute('''SELECT * FROM messages WHERE (sender = ? AND recipient = ?) 
                                     OR (sender = ? AND recipient = ?) ORDER BY timestamp ASC''', 
                                  (session['user'], current_chat, current_chat, session['user'])).fetchall()
            chat_info = conn.execute('SELECT username, avatar FROM users WHERE username = ?', (current_chat,)).fetchone()
            curr_group = {'id': current_chat, 'name': current_chat, 'type': 'dm', 'avatar': chat_info['avatar'] if chat_info else '👤'}
        else:
            messages = conn.execute('SELECT * FROM messages WHERE recipient IS NULL ORDER BY timestamp ASC').fetchall()
            curr_group = {'id': 'global', 'name': 'Общий чат', 'type': 'global', 'avatar': '🌍'}
    return render_template('index.html', me=me, users=users, messages=messages, curr_group=curr_group)

# Обрабатываем и /profile и /update_profile, чтобы не было 404
@app.route('/profile', methods=['GET', 'POST'])
@app.route('/update_profile', methods=['GET', 'POST'])
def profile():
    if 'user' not in session: return redirect(url_for('login'))
    with get_db() as conn:
        me = conn.execute('SELECT * FROM users WHERE username = ?', (session['user'],)).fetchone()
    
    if request.method == 'POST':
        bio = request.form.get('bio', '')
        theme = request.form.get('theme', 'light')
        avatar_val = me['avatar']
        
        file = request.files.get('avatar_file')
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = secure_filename(f"{session['user']}_{os.urandom(4).hex()}.{ext}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            avatar_val = f"/{app.config['UPLOAD_FOLDER']}/{filename}"
        
        with get_db() as conn:
            conn.execute('UPDATE users SET avatar = ?, bio = ?, theme = ? WHERE username = ?', 
                         (avatar_val, bio, theme, session['user']))
            conn.commit()
        return redirect(url_for('index'))
    return render_template('profile.html', me=me)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u, p = request.form.get('username', '').strip(), request.form.get('password')
        try:
            with get_db() as conn:
                conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (u, generate_password_hash(p)))
                conn.commit()
            return redirect(url_for('login'))
        except: flash("Никнейм занят")
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
        flash("Ошибка входа")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect():
    if 'user' in session: join_room(session['user'])

@socketio.on('send_msg')
def handle_msg(data):
    sender = session.get('user')
    if not sender: return
    msg, recipient = data.get('message'), data.get('recipient')
    db_recipient = None if recipient == 'global' else recipient
    with get_db() as conn:
        conn.execute('INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)', (sender, db_recipient, msg))
        conn.commit()
    out = {'sender': sender, 'message': msg, 'recipient': recipient}
    if db_recipient:
        emit('receive_msg', out, room=db_recipient)
        emit('receive_msg', out, room=sender)
    else:
        emit('receive_msg', out, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
