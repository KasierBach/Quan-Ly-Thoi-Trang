from flask import render_template, request, jsonify, flash, redirect, url_for
from app.database import get_db_connection
from .blueprint import admin_bp, admin_required

@admin_bp.route('/admin/reply_comment', methods=['POST'])
@admin_required
def admin_reply_comment():
    comment_id = request.form.get('comment_id', type=int)
    reply = request.form.get('reply')
    if not comment_id or not reply: return jsonify({'success': False, 'message': 'Invalid data'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE ProductComments SET AdminReply = %s, ReplyDate = CURRENT_TIMESTAMP WHERE CommentID = %s', (reply, comment_id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Success'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@admin_bp.route('/admin/contact_messages')
@admin_required
def admin_contact_messages():
    status_filter = request.args.get('status', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    query = 'SELECT * FROM ContactMessages'
    if status_filter: query += f" WHERE Status = '{status_filter}'"
    query += " ORDER BY SubmitDate DESC"
    cursor.execute(query)
    messages = cursor.fetchall()
    conn.close()
    return render_template('admin/contact_messages.html', messages=messages, current_status=status_filter)

@admin_bp.route('/admin/update_message_status', methods=['POST'])
@admin_required
def admin_update_message_status_json():
    message_id = request.form.get('message_id', type=int)
    new_status = request.form.get('status')
    if not message_id or not new_status: return jsonify({'success': False}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE ContactMessages SET Status = %s WHERE MessageID = %s', (new_status, message_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/admin/comments')
@admin_required
def admin_comments():
    filter_type = request.args.get('filter', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    
    if page < 1: page = 1
    if per_page not in [10, 15, 20, 50, 100]: per_page = 15

    conn = get_db_connection()
    cursor = conn.cursor()
    
    base_query = '''
        FROM ProductComments pc
        JOIN Customers c ON pc.CustomerID = c.CustomerID
        JOIN Products p ON pc.ProductID = p.ProductID
    '''
    where_clause = ""
    if filter_type == 'no_reply': where_clause = " WHERE pc.AdminReply IS NULL"
    elif filter_type == 'replied': where_clause = " WHERE pc.AdminReply IS NOT NULL"
    
    cursor.execute(f"SELECT COUNT(*) {base_query} {where_clause}")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * per_page
    
    query = f'''
        SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, pc.IsVisible,
               c.FullName AS CustomerName, p.ProductName, p.ProductID
        {base_query} {where_clause}
        ORDER BY pc.CommentDate DESC LIMIT %s OFFSET %s
    '''
    
    cursor.execute(query, (per_page, offset))
    comments = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('admin/comments.html', comments=comments, filter=filter_type, paging=paging_data)

@admin_bp.route('/admin/toggle_comment_visibility', methods=['POST'])
@admin_required
def admin_toggle_comment_visibility():
    comment_id = request.form.get('comment_id', type=int)
    visible = request.form.get('visible', type=int)
    if not comment_id: return jsonify({'success': False})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE ProductComments SET IsVisible = %s WHERE CommentID = %s', (bool(visible), comment_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()
