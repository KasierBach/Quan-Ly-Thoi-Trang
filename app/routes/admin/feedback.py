from flask import render_template, request, jsonify, flash, redirect, url_for
from app.services.feedback_service import FeedbackService
from app.services.main_service import MainService
from .blueprint import admin_bp, admin_required
from app.decorators import handle_db_errors

@admin_bp.route('/admin/reply_comment', methods=['POST'])
@admin_required
@handle_db_errors
def admin_reply_comment():
    cid, reply = request.form.get('comment_id', type=int), request.form.get('reply')
    if not cid or not reply: return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    res = FeedbackService.admin_reply_comment(cid, reply)
    return jsonify(res)

@admin_bp.route('/admin/contact_messages')
@admin_required
@handle_db_errors
def admin_contact_messages():
    status = request.args.get('status', '')
    messages = MainService.get_contact_messages(status)
    return render_template('admin/contact_messages.html', messages=messages, current_status=status)

@admin_bp.route('/admin/update_message_status', methods=['POST'])
@admin_required
@handle_db_errors
def admin_update_message_status_json():
    mid, status = request.form.get('message_id', type=int), request.form.get('status')
    if not mid or not status: return jsonify({'success': False}), 400
    
    res = MainService.update_contact_message_status(mid, status)
    return jsonify(res)

@admin_bp.route('/admin/comments')
@admin_required
@handle_db_errors
def admin_comments():
    args = request.args
    ftype, page, per_page = args.get('filter', ''), args.get('page', 1, type=int), args.get('per_page', 15, type=int)
    
    if page < 1: page = 1
    if per_page not in [10, 15, 20, 50, 100]: per_page = 15

    res = FeedbackService.get_admin_comments(ftype, page, per_page)
    return render_template('admin/comments.html', comments=res['comments'], filter=ftype, paging=res)

@admin_bp.route('/admin/toggle_comment_visibility', methods=['POST'])
@admin_required
@handle_db_errors
def admin_toggle_comment_visibility():
    cid, visible = request.form.get('comment_id', type=int), request.form.get('visible', type=int)
    if not cid: return jsonify({'success': False})
    
    res = FeedbackService.toggle_comment_visibility(cid, visible)
    return jsonify(res)
