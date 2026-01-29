
from flask import Blueprint, request, jsonify, session, render_template
from app.services.chat_service import ChatService
import uuid

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/api/chat/send', methods=['POST'])
def send_message():
    data = request.json
    content = data.get('content')
    session_id = data.get('session_id')
    
    if not content or not session_id:
        return jsonify({'error': 'Missing content or session_id'}), 400
        
    user_id = session.get('user_id') # Nếu đã login
    
    # User gửi
    result = ChatService.send_message('user', content, session_id, user_id)
    if result:
        return jsonify({'status': 'success', 'message': result})
    return jsonify({'error': 'Failed to send message'}), 500

@chat_bp.route('/api/chat/history', methods=['GET'])
def get_history():
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'error': 'Missing session_id'}), 400
        
    user_id = session.get('user_id')
    messages = ChatService.get_messages(session_id, user_id)
    return jsonify({'messages': messages})

# Admin routes
@chat_bp.route('/admin/chat/conversations', methods=['GET'])
def get_conversations():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    conversations = ChatService.get_all_conversations()
    return jsonify({'conversations': conversations})

@chat_bp.route('/admin/chat')
def admin_chat_dashboard():
    if not session.get('is_admin'):
        return render_template('404.html'), 404
        
    return render_template('admin/chat_dashboard.html')

@chat_bp.route('/api/chat/admin/send', methods=['POST'])
def admin_reply():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    content = data.get('content')
    session_id = data.get('session_id')
    
    if not content or not session_id:
        return jsonify({'error': 'Missing content or session_id'}), 400
        
    result = ChatService.send_message('admin', content, session_id, user_id=None) # Admin reply
    if result:
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Failed to send'}), 500
