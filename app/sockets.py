"""
Socket.IO Event Handlers for Real-time Chat
Handles WebSocket events for messaging, typing indicators, reactions, etc.
"""
from flask import request, session
from flask_socketio import emit, join_room, leave_room
from app.services.chat_service import ChatService
import logging

logger = logging.getLogger(__name__)

class ChatSocketHandlers:
    def __init__(self, socketio):
        self.socketio = socketio

    def register_all(self):
        """Register all Socket.IO event handlers."""
        self.socketio.on('connect')(self.handle_connect)
        self.socketio.on('disconnect')(self.handle_disconnect)
        self.socketio.on('join_conversation')(self.handle_join_conversation)
        self.socketio.on('leave_conversation')(self.handle_leave_conversation)
        self.socketio.on('send_message')(self.handle_message)
        self.socketio.on('admin_reply')(self.handle_admin_reply)
        self.socketio.on('typing')(self.handle_typing)
        self.socketio.on('stop_typing')(self.handle_stop_typing)
        self.socketio.on('admin_typing')(self.handle_admin_typing)
        self.socketio.on('admin_stop_typing')(self.handle_admin_stop_typing)
        self.socketio.on('add_reaction')(self.handle_add_reaction)
        self.socketio.on('remove_reaction')(self.handle_remove_reaction)
        self.socketio.on('recall_message')(self.handle_recall_message)
        self.socketio.on('pin_message')(self.handle_pin_message)
        self.socketio.on('unpin_message')(self.handle_unpin_message)
        self.socketio.on('mark_read')(self.handle_mark_read)
        self.socketio.on('update_conversation_settings')(self.handle_update_conversation_settings)
        self.socketio.on('update_participant_settings')(self.handle_update_participant_settings)

    def handle_connect(self):
        session_id = request.args.get('session_id')
        user_id = session.get('user_id')
        if session_id:
            join_room(session_id)
            logger.info(f"Client connected to room: {session_id}")
        if session.get('is_admin'):
            join_room('admin_room')
        if user_id:
            ChatService.update_last_seen(user_id)
            emit('user_online', {'user_id': user_id}, broadcast=True)

    def handle_disconnect(self):
        user_id = session.get('user_id')
        if user_id:
            ChatService.update_last_seen(user_id)
            emit('user_offline', {'user_id': user_id}, broadcast=True)

    def handle_join_conversation(self, data):
        conv_id = data.get('conversation_id')
        if not conv_id: return
        
        # If it's a numeric ID, it's a real Conversation. If it's a string/UUID, it's a guest Session.
        if isinstance(conv_id, int) or (isinstance(conv_id, str) and conv_id.isdigit()):
            room = f'conv_{conv_id}'
            user_id = session.get('user_id')
            if user_id:
                ChatService.mark_as_read(int(conv_id), user_id)
        else:
            room = conv_id # It's a session_id
            
        join_room(room)
        logger.info(f"Socket joined room: {room}")

    def handle_leave_conversation(self, data):
        conv_id = data.get('conversation_id')
        if conv_id:
            leave_room(f'conv_{conv_id}')

    def handle_message(self, data):
        content = data.get('content', '').strip()
        sid = data.get('session_id')
        cid = data.get('conversation_id')
        uid = session.get('user_id')
        mtype = data.get('message_type', 'text')
        
        if not content or not sid:
            return emit('error', {'message': 'Missing content or session_id'})

        # If cid is a string UUID, we treat it as no cid (it's a guest session) for DB storage, 
        # but we use it for room routing.
        real_cid = None
        if cid and (isinstance(cid, int) or (isinstance(cid, str) and cid.isdigit())):
            real_cid = int(cid)

        res = ChatService.send_message(
            sender_type='user', content=content, session_id=sid,
            user_id=uid, conversation_id=real_cid, message_type=mtype,
            reply_to_id=data.get('reply_to_id')
        )
        
        if res['success']:
            msg_data = {
                'id': res['id'], 'session_id': sid, 'conversation_id': cid,
                'content': content, 'sender': 'user', 'sender_id': uid,
                'message_type': mtype, 'timestamp': res['timestamp'],
                'reply_to_id': data.get('reply_to_id'),
                'parent_content': res.get('parent_content'),
                'parent_sender_type': res.get('parent_sender_type')
            }
            self.socketio.emit('new_message', msg_data, room='admin_room')
            
            # Emit to specific room (either conv_ID or just session_id)
            room = f'conv_{real_cid}' if real_cid else sid
            self.socketio.emit('new_message', msg_data, room=room)
            
            emit('message_sent', {'status': 'success', 'id': res['id']})

    def handle_admin_reply(self, data):
        if not session.get('is_admin'): return
        content = data.get('content', '').strip()
        sid = data.get('session_id')
        cid = data.get('conversation_id')
        if not content or not sid: return

        res = ChatService.send_message(
            sender_type='admin', content=content, session_id=sid,
            conversation_id=cid, message_type=data.get('message_type', 'text')
        )

        if res['success']:
            msg_data = {
                'id': res['id'], 'content': content, 'sender': 'admin',
                'message_type': data.get('message_type', 'text'), 'timestamp': res['timestamp'],
                'reply_to_id': data.get('reply_to_id'),
                'parent_content': res.get('parent_content'),
                'parent_sender_type': res.get('parent_sender_type')
            }
            self.socketio.emit('receive_message', msg_data, room=sid)
            if cid:
                self.socketio.emit('new_message', msg_data, room=f'conv_{cid}')

    def handle_typing(self, data):
        sid = data.get('session_id')
        cid = data.get('conversation_id')
        t_data = {'session_id': sid, 'user_id': session.get('user_id'), 'user_name': session.get('fullname', 'Người dùng')}
        self.socketio.emit('typing', t_data, room='admin_room')
        if cid:
            self.socketio.emit('typing', t_data, room=f'conv_{cid}')

    def handle_stop_typing(self, data):
        sid = data.get('session_id')
        cid = data.get('conversation_id')
        t_data = {'session_id': sid, 'user_id': session.get('user_id')}
        self.socketio.emit('stop_typing', t_data, room='admin_room')
        if cid:
            self.socketio.emit('stop_typing', t_data, room=f'conv_{cid}')

    def handle_admin_typing(self, data):
        if session.get('is_admin'):
            self.socketio.emit('admin_typing', {}, room=data.get('session_id'))

    def handle_admin_stop_typing(self, data):
        if session.get('is_admin'):
            self.socketio.emit('admin_stopped_typing', {}, room=data.get('session_id'))

    def handle_add_reaction(self, data):
        mid, e, uid = data.get('message_id'), data.get('emoji'), session.get('user_id')
        if not all([mid, e, uid]): return
        if ChatService.add_reaction(mid, uid, e):
            r_data = {'message_id': mid, 'emoji': e, 'user_id': uid, 'action': 'add'}
            self._broadcast_reaction(r_data, data)

    def handle_remove_reaction(self, data):
        mid, e, uid = data.get('message_id'), data.get('emoji'), session.get('user_id')
        if not all([mid, e, uid]): return
        if ChatService.remove_reaction(mid, uid, e):
            r_data = {'message_id': mid, 'emoji': e, 'user_id': uid, 'action': 'remove'}
            self._broadcast_reaction(r_data, data)

    def _broadcast_reaction(self, r_data, input_data):
        cid, sid = input_data.get('conversation_id'), input_data.get('session_id')
        if cid: self.socketio.emit('reaction_update', r_data, room=f'conv_{cid}')
        if sid: self.socketio.emit('reaction_update', r_data, room=sid)
        self.socketio.emit('reaction_update', r_data, room='admin_room')

    def handle_recall_message(self, data):
        mid, uid = data.get('message_id'), session.get('user_id')
        if not mid or not uid: return
        if ChatService.recall_message(mid, uid):
            r_data = {'message_id': mid, 'recalled': True}
            cid, sid = data.get('conversation_id'), data.get('session_id')
            if cid: self.socketio.emit('message_recalled', r_data, room=f'conv_{cid}')
            if sid: self.socketio.emit('message_recalled', r_data, room=sid)
            self.socketio.emit('message_recalled', r_data, room='admin_room')

    def handle_pin_message(self, data):
        mid, cid, uid = data.get('message_id'), data.get('conversation_id'), session.get('user_id')
        if mid and cid and uid:
            try:
                if ChatService.pin_message(int(cid), int(mid), int(uid)):
                    self.socketio.emit('message_pinned', {'message_id': mid, 'conversation_id': cid}, room=f'conv_{cid}')
            except Exception as e:
                logger.error(f"Pin failed: {e}")

    def handle_unpin_message(self, data):
        mid, cid = data.get('message_id'), data.get('conversation_id')
        if mid and cid:
            try:
                if ChatService.unpin_message(int(cid), int(mid)):
                    self.socketio.emit('message_unpinned', {'message_id': mid, 'conversation_id': cid}, room=f'conv_{cid}')
            except Exception as e:
                logger.error(f"Unpin failed: {e}")

    def handle_mark_read(self, data):
        cid, uid = data.get('conversation_id'), session.get('user_id')
        if cid and uid:
            ChatService.mark_as_read(cid, uid)
            self.socketio.emit('messages_read', {'conversation_id': cid, 'user_id': uid}, room=f'conv_{cid}')

    def handle_update_conversation_settings(self, data):
        cid = data.get('conversation_id')
        settings = data.get('settings')
        if cid and settings:
            self.socketio.emit('conversation_settings_updated', {'conversation_id': cid, 'settings': settings}, room=f'conv_{cid}')

    def handle_update_participant_settings(self, data):
        cid = data.get('conversation_id')
        uid = data.get('user_id')
        settings = data.get('settings')
        if cid and uid and settings:
            self.socketio.emit('participant_settings_updated', {'conversation_id': cid, 'user_id': uid, 'settings': settings}, room=f'conv_{cid}')

def register_socket_events(socketio):

    handlers = ChatSocketHandlers(socketio)
    handlers.register_all()
