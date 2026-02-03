"""
Chat Routes - API endpoints and page routes for the messaging system.
Handles message sending, file uploads, reactions, and page rendering.
"""
from flask import Blueprint, request, jsonify, session, render_template, current_app, url_for, redirect
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.attachment_service import AttachmentService
from werkzeug.utils import secure_filename
import uuid
import os

chat_bp = Blueprint('chat', __name__)

# --- Configuration & Helpers ---
ALLOWED_EXTENSIONS = {
    'image': {'png', 'jpg', 'jpeg', 'gif', 'webp'},
    'video': {'mp4', 'webm', 'mov'},
    'audio': {'mp3', 'wav', 'ogg', 'm4a', 'webm'},  # Added audio support
    'file': {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip', 'rar'}
}

def allowed_file(filename, file_type='image'):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return ext in ALLOWED_EXTENSIONS.get(file_type, set())

def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    for ftype, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions: return ftype
    return 'file'

def normalize_user(u):
    """Normalize user object from DB results."""
    uid = u.get('id') or u.get('customerid') or (u[0] if isinstance(u, (list, tuple)) else None)
    return {
        'id': uid,
        'name': u.get('name') or u.get('fullname') or (u[1] if isinstance(u, (list, tuple)) else None),
        'email': u.get('email') or (u[2] if isinstance(u, (list, tuple)) else None),
        'avatar': u.get('avatar') or (u[3] if isinstance(u, (list, tuple)) else None)
    }

# --- Page Routes ---

@chat_bp.route('/messages')
def messages_page():
    return render_template('messages.html')

@chat_bp.route('/admin/messages')
def admin_messages_page():
    if not session.get('is_admin'): return render_template('404.html'), 404
    return render_template('admin/messages.html')

@chat_bp.route('/admin/chat/dashboard')
def admin_chat_dashboard():
    if not session.get('is_admin'): return render_template('404.html'), 404
    return redirect(url_for('chat.messages_page'))

@chat_bp.route('/admin/chat/conversations')
def admin_get_conversations():
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    
    from app.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch unique session IDs and their latest message info
        cursor.execute('''
            SELECT session_id, user_id, MAX(created_at) as last_time,
                   (SELECT content FROM Messages m2 WHERE m2.session_id = m.session_id ORDER BY created_at DESC LIMIT 1) as last_message,
                   (SELECT sender_type FROM Messages m2 WHERE m2.session_id = m.session_id ORDER BY created_at DESC LIMIT 1) as last_sender
            FROM Messages m
            WHERE session_id IS NOT NULL
            GROUP BY session_id, user_id
            ORDER BY last_time DESC
        ''')
        conversations = []
        for row in cursor.fetchall():
            conversations.append({
                'session_id': row[0],
                'user_id': row[1],
                'last_time': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else None,
                'last_message': row[3],
                'last_sender': row[4]
            })
        return jsonify({'conversations': conversations})
    finally:
        conn.close()

@chat_bp.route('/api/chat/admin/send', methods=['POST'])
def admin_send_message():
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    content = data.get('content')
    sid = data.get('session_id')
    if not content or not sid: return jsonify({'error': 'Missing data'}), 400
    
    res = ChatService.send_message(
        sender_type='admin',
        content=content,
        session_id=sid,
        user_id=None
    )
    return jsonify(res)

# --- API Endpoints ---

@chat_bp.route('/api/users/suggested', methods=['GET'])
def get_suggested_users():
    uid = session.get('user_id')
    if not uid: return jsonify({'users': []})
    users = ConversationService.get_suggested_users(uid)
    return jsonify({'users': [normalize_user(u) for u in users]})

@chat_bp.route('/api/users/search', methods=['GET'])
def search_users():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Not logged in'}), 401
    query = request.args.get('q', '').strip()
    if len(query) < 2: return jsonify({'users': []})
    users = ConversationService.search_users(uid, query)
    return jsonify({'users': [normalize_user(u) for u in users]})

@chat_bp.route('/api/conversations', methods=['GET', 'POST'])
def handle_conversations():
    uid = session.get('user_id')
    is_admin = session.get('is_admin')
    if not uid: return jsonify({'error': 'Not logged in'}), 401
    
    if request.method == 'POST':
        data = request.json
        res = ConversationService.create_conversation(
            conversation_type=data.get('type', 'group'), 
            name=data.get('name'), 
            created_by=uid
        )
        return jsonify(res), (200 if res['success'] else 500)
        
    # Get regular user conversations
    conversations = ConversationService.get_user_conversations(uid)
    result = []
    seen_convs = set()

    for conv in conversations:
        c = dict(conv) if hasattr(conv, 'keys') else conv
        seen_convs.add(c['id'])
        if c.get('type') == 'private':
            others = [p for p in ConversationService.get_participants(c['id']) if p['id'] != uid]
            if others:
                c['name'] = others[0]['name']
                c['avatar'] = others[0].get('avatar')
        result.append(c)

    # If admin, also include guest support sessions from Messages
    if is_admin:
        from app.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Find unique session_ids that are not already tied to a conversation the admin is in
            cursor.execute('''
                SELECT session_id, MAX(created_at) as last_time,
                       (SELECT content FROM Messages m2 WHERE m2.session_id = m.session_id ORDER BY created_at DESC LIMIT 1) as last_message
                FROM Messages m
                WHERE session_id IS NOT NULL AND conversation_id IS NULL
                GROUP BY session_id
                ORDER BY last_time DESC
            ''')
            for row in cursor.fetchall():
                sid = row[0]
                result.append({
                    'id': sid, # Use session_id as the unique ID for the UI
                    'session_id': sid,
                    'name': f"Khách {sid[:8]}",
                    'type': 'support',
                    'last_message': row[2],
                    'last_message_at': row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else None,
                    'is_online': True 
                })
        finally:
            conn.close()

    return jsonify({'conversations': result})

@chat_bp.route('/api/chat/send', methods=['POST'])
def handle_chat_send():
    data = request.json
    content = data.get('content')
    sid = data.get('session_id')
    cid = data.get('conversation_id')
    uid = session.get('user_id')
    
    if not content or not sid:
        return jsonify({'error': 'Missing content or session_id'}), 400
        
    res = ChatService.send_message(
        sender_type='user',
        content=content,
        session_id=sid,
        user_id=uid,
        conversation_id=cid
    )
    return jsonify(res)

@chat_bp.route('/api/conversations/direct', methods=['POST'])
def handle_direct_chat():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json(silent=True) or {}
    target_id = data.get('user_id')
    if not target_id: return jsonify({'error': 'User ID required'}), 400
    
    existing = ConversationService.get_direct_conversation(uid, target_id)
    if existing: return jsonify({'conversation': dict(existing)})
    
    res = ConversationService.create_conversation(conversation_type='private', created_by=uid)
    if res['success']:
        ConversationService.add_participant(res['id'], target_id)
        return jsonify({'conversation': {'id': res['id']}})
    return jsonify(res), 500

@chat_bp.route('/api/chat/history', methods=['GET'])
def get_history():
    sid = request.args.get('session_id')
    cid = request.args.get('conversation_id')
    real_cid = None
    real_sid = sid
    
    if cid:
        if isinstance(cid, int) or (isinstance(cid, str) and cid.isdigit()):
            real_cid = int(cid)
        else:
            # It's a session_id passed as cid (for guest chats in the UI)
            real_sid = cid
            real_cid = None

    messages = ChatService.get_messages(
        session_id=real_sid or '',
        user_id=session.get('user_id'),
        conversation_id=real_cid,
        limit=request.args.get('limit', 50, type=int),
        before_id=request.args.get('before_id', type=int)
    )
    return jsonify({'messages': messages})

@chat_bp.route('/api/chat/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    sid = request.form.get('session_id')
    cid = request.form.get('conversation_id')
    if not sid: return jsonify({'error': 'No session_id'}), 400
    
    ftype = get_file_type(file.filename)
    if not allowed_file(file.filename, ftype): return jsonify({'error': 'Invalid file type'}), 400
    
    # Save file
    fname = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    folder = os.path.join(current_app.root_path, 'static', 'uploads', 'chat')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, fname)
    file.save(path)
    
    url = url_for('static', filename=f'uploads/chat/{fname}', _external=True)
    uid = session.get('user_id')
    
    res = ChatService.send_message(
        sender_type='user', content=f'[{ftype.upper()}] {file.filename}',
        session_id=sid, user_id=uid, conversation_id=int(cid) if cid else None,
        message_type=ftype
    )
    
    if res['success']:
        AttachmentService.add_attachment(res['id'], url, file.filename, ftype, os.path.getsize(path))
        return jsonify({'status': 'success', 'file_url': url})
    
    os.remove(path)
    return jsonify({'error': 'Failed'}), 500

# --- Basic Crud (Reactions, Pins, Recall) ---

@chat_bp.route('/api/chat/messages/<int:mid>/reactions', methods=['POST', 'DELETE', 'GET'])
def manage_reactions(mid):
    uid = session.get('user_id')
    if not uid and request.method != 'GET': return jsonify({'error': 'Auth needed'}), 401
    
    if request.method == 'POST':
        emoji = request.json.get('emoji')
        return jsonify({'status': 'success'}) if ChatService.add_reaction(mid, uid, emoji) else (jsonify({'error': 'Fail'}), 500)
    elif request.method == 'DELETE':
        emoji = request.args.get('emoji')
        return jsonify({'status': 'success'}) if ChatService.remove_reaction(mid, uid, emoji) else (jsonify({'error': 'Fail'}), 500)
    return jsonify({'reactions': ChatService.get_reactions(mid)})

@chat_bp.route('/api/chat/conversations/<cid>/pinned', methods=['GET'])
def get_pinned_messages(cid):
    if not str(cid).isdigit(): return jsonify({'pinned': []})
    return jsonify({'pinned': ChatService.get_pinned_messages(int(cid))})

@chat_bp.route('/api/chat/pin', methods=['POST'])
def pin_message():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    data = request.json
    mid, cid = data.get('message_id'), data.get('conversation_id')
    if not str(cid).isdigit(): return jsonify({'error': 'Unsupported for guest chats'}), 400
    return jsonify({'status': 'success'}) if ChatService.pin_message(int(cid), mid, uid) else (jsonify({'error': 'Fail'}), 500)

@chat_bp.route('/api/chat/unpin', methods=['POST'])
def unpin_message():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    data = request.json
    mid, cid = data.get('message_id'), data.get('conversation_id')
    if not str(cid).isdigit(): return jsonify({'error': 'Unsupported for guest chats'}), 400
    return jsonify({'status': 'success'}) if ChatService.unpin_message(int(cid), mid) else (jsonify({'error': 'Fail'}), 500)

@chat_bp.route('/api/chat/messages/<int:mid>/recall', methods=['POST'])
def recall_message(mid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    return jsonify({'status': 'success'}) if ChatService.recall_message(mid, uid) else (jsonify({'error': 'Fail'}), 400)

@chat_bp.route('/api/conversations/<cid>/leave', methods=['POST'])
def leave_conversation(cid):
    uid = session.get('user_id')
    is_admin = session.get('is_admin')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    
    if not str(cid).isdigit():
        # It's a session_id. Only admins can "delete" these guest chats.
        if not is_admin: return jsonify({'error': 'Unauthorized'}), 403
        return jsonify({'status': 'success'}) if ChatService.delete_session_messages(cid) else (jsonify({'error': 'Fail'}), 500)
        
    return jsonify({'status': 'success'}) if ConversationService.leave_conversation(int(cid), uid) else (jsonify({'error': 'Fail'}), 500)

@chat_bp.route('/api/conversations/<cid>/read', methods=['POST'])
def mark_read(cid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    if not str(cid).isdigit(): return jsonify({'status': 'success'}) # Ignore for guest chats
    return jsonify({'status': 'success'}) if ConversationService.mark_as_read(int(cid), uid) else (jsonify({'error': 'Fail'}), 500)

@chat_bp.route('/api/conversations/<cid>/participants', methods=['GET'])
def get_participants(cid):
    if not str(cid).isdigit(): return jsonify({'participants': []})
    return jsonify({'participants': ConversationService.get_participants(int(cid))})

@chat_bp.route('/api/conversations/<int:cid>/settings', methods=['PATCH'])
def update_conversation_settings(cid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    
    # Check if user is a participant (optional but recommended)
    participants = ConversationService.get_participants(cid)
    if not any(p['id'] == uid for p in participants):
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    if ConversationService.update_conversation_settings(cid, data):
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Fail'}), 500

@chat_bp.route('/api/conversations/<int:cid>/participants/me', methods=['PATCH'])
def update_my_participant_settings(cid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    
    data = request.json
    if ConversationService.update_participant_settings(cid, uid, data):
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Fail'}), 500

@chat_bp.route('/api/conversations/<int:cid>/attachments', methods=['GET'])
def get_conversation_attachments(cid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    
    # Check if user is a participant
    participants = ConversationService.get_participants(cid)
    if not any(p['id'] == uid for p in participants):
        return jsonify({'error': 'Unauthorized'}), 403
        
    ftype = request.args.get('type')
    attachments = ChatService.get_attachments(cid, ftype)
    return jsonify({'attachments': attachments})
