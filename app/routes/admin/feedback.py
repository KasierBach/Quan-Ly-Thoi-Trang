from flask import abort, current_app, jsonify, render_template, request
from markupsafe import escape

from app.decorators import handle_db_errors
from app.services.feedback_service import FeedbackService
from app.services.main_service import MainService
from app.utils import send_email
from app.validation import ValidationError, email_address, positive_int, required_text

from .blueprint import admin_bp, admin_required, paging_args, service_response


def _date_text(value):
    return value.strftime('%d/%m/%Y %H:%M') if value else ''


@admin_bp.route('/admin/reply_comment', methods=['POST'])
@admin_required
@handle_db_errors
def admin_reply_comment():
    try:
        comment_id = positive_int(request.form.get('comment_id'), 'Bình luận', max_value=2147483647)
        reply = required_text(request.form.get('reply'), 'Phản hồi', 5000)
        return service_response(FeedbackService.admin_reply_comment(comment_id, reply))
    except ValidationError:
        return jsonify(success=False, message='Bình luận hoặc nội dung phản hồi không hợp lệ'), 400


@admin_bp.route('/admin/contact_messages')
@admin_required
@handle_db_errors
def admin_contact_messages():
    status = request.args.get('status', '')
    page, per_page = paging_args(request.args)
    try:
        result = MainService.get_contact_messages(status, page, per_page)
    except ValidationError as exc:
        abort(400, description=str(exc))
    message_data = {
        str(row.MessageID): {
            'id': row.MessageID,
            'name': row.Name,
            'email': row.Email,
            'subject': row.Subject or 'Không có tiêu đề',
            'message': row.Message,
            'date': _date_text(row.SubmitDate),
            'status': row.Status,
        }
        for row in result['messages']
    }
    return render_template(
        'admin/contact_messages.html',
        messages=result['messages'],
        current_status=status,
        paging=result,
        message_data=message_data,
        email_enabled=not current_app.testing
        and not current_app.config.get('MAIL_SUPPRESS_SEND')
        and bool(current_app.config.get('MAIL_SERVER') and current_app.config.get('MAIL_DEFAULT_SENDER')),
    )


@admin_bp.route('/admin/update_message_status', methods=['POST'])
@admin_required
@handle_db_errors
def admin_update_message_status_json():
    try:
        return service_response(
            MainService.update_contact_message_status(request.form.get('message_id'), request.form.get('status'))
        )
    except ValidationError:
        return jsonify(success=False, message='Tin nhắn hoặc trạng thái không hợp lệ'), 400


@admin_bp.route('/admin/reply_contact_message', methods=['POST'])
@admin_required
@handle_db_errors
def admin_reply_contact_message():
    try:
        message_id = positive_int(request.form.get('message_id'), 'Tin nhắn', max_value=2147483647)
        reply = required_text(request.form.get('reply'), 'Phản hồi', 5000)
    except ValidationError:
        return jsonify(success=False, message='Tin nhắn hoặc nội dung phản hồi không hợp lệ'), 400
    message = MainService.get_contact_message(message_id)
    if not message:
        return jsonify({'success': False, 'message': 'Tin nhắn không tồn tại'}), 404
    try:
        # Bind the recipient to the persisted contact, never an arbitrary form address.
        recipient = email_address(message.Email)
    except ValidationError:
        return jsonify({'success': False, 'message': 'Địa chỉ email trong tin nhắn không hợp lệ'}), 409
    if (
        current_app.testing
        or current_app.config.get('MAIL_SUPPRESS_SEND')
        or not current_app.config.get('MAIL_SERVER')
        or not current_app.config.get('MAIL_DEFAULT_SENDER')
    ):
        return jsonify({'success': False, 'message': 'Gửi email chưa được cấu hình hoặc đang tắt'}), 503
    if not send_email(recipient, '[FashionStore] Phản hồi liên hệ', f'<pre>{escape(reply)}</pre>'):
        return jsonify({'success': False, 'message': 'Không thể gửi phản hồi qua email. Vui lòng thử lại sau.'}), 502
    result = MainService.update_contact_message_status(message_id, 'Answered')
    if not result['success']:
        return jsonify({'success': False, 'message': 'Email đã gửi nhưng không thể cập nhật trạng thái tin nhắn.'}), 500
    return jsonify({'success': True, 'message': 'Đã gửi phản hồi đến máy chủ email và cập nhật trạng thái'})


@admin_bp.route('/admin/comments')
@admin_required
@handle_db_errors
def admin_comments():
    filter_type = request.args.get('filter', '')
    page, per_page = paging_args(request.args, default=15, allowed=(10, 15, 20, 50, 100))
    try:
        result = FeedbackService.get_admin_comments(filter_type, page, per_page)
    except ValidationError as exc:
        abort(400, description=str(exc))
    comment_data = {
        str(row.CommentID): {
            'id': row.CommentID,
            'productName': row.ProductName,
            'productId': row.ProductID,
            'customerName': row.CustomerName,
            'content': row.Content,
            'commentDate': _date_text(row.CommentDate),
            'adminReply': row.AdminReply or '',
            'replyDate': _date_text(row.ReplyDate),
            'isVisible': bool(row.IsVisible),
        }
        for row in result['comments']
    }
    return render_template(
        'admin/comments.html', comments=result['comments'], filter=filter_type, paging=result, comment_data=comment_data
    )


@admin_bp.route('/admin/toggle_comment_visibility', methods=['POST'])
@admin_required
@handle_db_errors
def admin_toggle_comment_visibility():
    try:
        return service_response(
            FeedbackService.toggle_comment_visibility(request.form.get('comment_id'), request.form.get('visible'))
        )
    except ValidationError:
        return jsonify(success=False, message='Bình luận hoặc trạng thái hiển thị không hợp lệ'), 400
