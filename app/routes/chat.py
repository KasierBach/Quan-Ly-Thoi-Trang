from flask import Blueprint, request, jsonify, session, render_template, current_app, url_for, redirect
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.attachment_service import AttachmentService
from app.decorators import handle_db_errors, login_required
from werkzeug.utils import secure_filename
import uuid
import os

chat_bp = Blueprint('chat', __name__)

# --- Configuration & Helpers ---
ALLOWED_EXTENSIONS = {
    'image': {'png', 'jpg', 'jpeg', 'gif', 'webp'},
    'video': {'mp4', 'webm', 'mov'},
    'audio': {'mp3', 'wav', 'ogg', 'm4a', 'webm'},
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
    return render_template('messages.html')

@chat_bp.route('/admin/chat/conversations')
@handle_db_errors
def admin_get_conversations():
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    return jsonify({'conversations': ConversationService.get_guest_conversations()})

@chat_bp.route('/api/chat/admin/send', methods=['POST'])
@handle_db_errors
def admin_send_message():
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    data = request.json
    content, sid = data.get('content'), data.get('session_id')
    if not content or not sid: return jsonify({'error': 'Missing data'}), 400
    
    return jsonify(ChatService.send_message(sender_type='admin', content=content, session_id=sid))

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
@handle_db_errors
def handle_conversations():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Not logged in'}), 401
    
    if request.method == 'POST':
        data = request.json
        res = ConversationService.create_conversation(
            conversation_type=data.get('type', 'group'), name=data.get('name'), created_by=uid
        )
        return jsonify(res), (200 if res['success'] else 500)
        
    result = ConversationService.get_user_conversations(uid)
    if session.get('is_admin'):
        result.extend(ConversationService.get_guest_conversations())
    return jsonify({'conversations': result})

@chat_bp.route('/api/conversations/<int:cid>', methods=['GET'])
@handle_db_errors
def get_conversation_details(cid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Not logged in'}), 401
    
    participants = ConversationService.get_participants(cid)
    if not any(p['id'] == uid for p in participants) and not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
        
    conv = ConversationService.get_conversation(cid)
    return jsonify(conv) if conv else (jsonify({'error': 'Not found'}), 404)

@chat_bp.route('/api/chat/send', methods=['POST'])
@handle_db_errors
def handle_chat_send():
    data = request.json
    content, sid, cid = data.get('content'), data.get('session_id'), data.get('conversation_id')
    if not content or not sid: return jsonify({'error': 'Missing data'}), 400
        
    return jsonify(ChatService.send_message(
        sender_type='user', content=content, session_id=sid, 
        user_id=session.get('user_id'), conversation_id=cid
    ))

@chat_bp.route('/api/conversations/direct', methods=['POST'])
@handle_db_errors
def handle_direct_chat():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Not logged in'}), 401
    
    target_id = (request.get_json(silent=True) or {}).get('user_id')
    if not target_id: return jsonify({'error': 'User ID required'}), 400
    
    existing = ConversationService.get_direct_conversation(uid, target_id)
    if existing: return jsonify({'conversation': dict(existing)})
    
    res = ConversationService.create_conversation(conversation_type='private', created_by=uid)
    if res['success']:
        ConversationService.add_participant(res['id'], target_id)
        return jsonify({'conversation': {'id': res['id']}})
    return jsonify(res), 500

@chat_bp.route('/api/chat/history', methods=['GET'])
@handle_db_errors
def get_history():
    sid, cid = request.args.get('session_id'), request.args.get('conversation_id')
    real_cid = int(cid) if cid and str(cid).isdigit() else None
    real_sid = cid if cid and not str(cid).isdigit() else sid

    messages = ChatService.get_messages(
        session_id=real_sid or '', user_id=session.get('user_id'),
        conversation_id=real_cid, limit=request.args.get('limit', 50, type=int),
        before_id=request.args.get('before_id', type=int)
    )
    return jsonify({'messages': messages})

@chat_bp.route('/api/chat/upload', methods=['POST'])
@handle_db_errors
def upload_file():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file, sid, cid = request.files['file'], request.form.get('session_id'), request.form.get('conversation_id')
    if not sid: return jsonify({'error': 'No session_id'}), 400
    
    ftype = get_file_type(file.filename)
    if not allowed_file(file.filename, ftype): return jsonify({'error': 'Invalid file type'}), 400
    
    fname = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    folder = os.path.join(current_app.root_path, 'static', 'uploads', 'chat')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, fname)
    file.save(path)
    
    uid, url = session.get('user_id'), url_for('static', filename=f'uploads/chat/{fname}', _external=True)
    res = ChatService.send_message(
        sender_type='user', content=f'[{ftype.upper()}] {file.filename}',
        session_id=sid, user_id=uid, conversation_id=int(cid) if (cid and str(cid).isdigit()) else None,
        message_type=ftype
    )
    
    if res['success']:
        AttachmentService.add_attachment(res['id'], url, file.filename, ftype, os.path.getsize(path))
        return jsonify({'status': 'success', 'file_url': url})
    
    if os.path.exists(path): os.remove(path)
    return jsonify({'error': 'Failed'}), 500

@chat_bp.route('/api/chat/messages/<int:mid>/reactions', methods=['POST', 'DELETE', 'GET'])
@handle_db_errors
def manage_reactions(mid):
    uid = session.get('user_id')
    if not uid and request.method != 'GET': return jsonify({'error': 'Auth needed'}), 401
    
    if request.method == 'POST':
        return jsonify({'status': 'success'}) if ChatService.add_reaction(mid, uid, request.json.get('emoji')) else (jsonify({'error': 'Fail'}), 500)
    if request.method == 'DELETE':
        return jsonify({'status': 'success'}) if ChatService.remove_reaction(mid, uid, request.args.get('emoji')) else (jsonify({'error': 'Fail'}), 500)
    return jsonify({'reactions': ChatService.get_reactions(mid)})

@chat_bp.route('/api/chat/pin', methods=['POST'])
@handle_db_errors
def pin_message():
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    mid, cid = request.json.get('message_id'), request.json.get('conversation_id')
    if not str(cid).isdigit(): return jsonify({'error': 'Unsupported'}), 400
    return jsonify({'status': 'success'}) if ChatService.pin_message(int(cid), mid, uid) else (jsonify({'error': 'Fail'}), 500)

@chat_bp.route('/api/chat/messages/<int:mid>/recall', methods=['POST'])
@handle_db_errors
def recall_message(mid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    return jsonify({'status': 'success'}) if ChatService.recall_message(mid, uid) else (jsonify({'error': 'Fail'}), 400)

@chat_bp.route('/api/conversations/<cid>/leave', methods=['POST'])
@handle_db_errors
def leave_conversation(cid):
    uid, is_admin = session.get('user_id'), session.get('is_admin')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    
    if not str(cid).isdigit():
        if not is_admin: return jsonify({'error': 'Unauthorized'}), 403
        return jsonify({'status': 'success'}) if ChatService.delete_session_messages(cid) else (jsonify({'error': 'Fail'}), 500)
        
    return jsonify({'status': 'success'}) if ConversationService.leave_conversation(int(cid), uid) else (jsonify({'error': 'Fail'}), 500)

@chat_bp.route('/api/conversations/<cid>/read', methods=['POST'])
@handle_db_errors
def mark_read(cid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    if not str(cid).isdigit(): return jsonify({'status': 'success'})
    return jsonify({'status': 'success'}) if ConversationService.mark_as_read(int(cid), uid) else (jsonify({'error': 'Fail'}), 500)

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

@chat_bp.route('/api/conversations/<int:cid>/participants/<int:target_uid>', methods=['PATCH'])
def update_participant_settings_specific(cid, target_uid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error': 'Auth needed'}), 401
    
    # Check if calling user is a participant
    participants = ConversationService.get_participants(cid)
    if not any(p['id'] == uid for p in participants):
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    if ConversationService.update_participant_settings(cid, target_uid, data):
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
