# Hủy đơn hàng
@app.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để hủy đơn hàng'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Kiểm tra đơn hàng có tồn tại và thuộc về người dùng
        cursor.execute('''
            SELECT Status, CustomerID FROM Orders 
            WHERE OrderID = ?
        ''', order_id)
        order = cursor.fetchone()
        
        if not order:
            return jsonify({'success': False, 'message': 'Đơn hàng không tồn tại'})
        
        if order.CustomerID != session['user_id']:
            return jsonify({'success': False, 'message': 'Bạn không có quyền hủy đơn hàng này'})
        
        if order.Status != 'Pending':
            return jsonify({'success': False, 'message': 'Chỉ có thể hủy đơn hàng ở trạng thái Đang xử lý'})
        
        # Cập nhật trạng thái đơn hàng thành 'Cancelled'
        cursor.execute('''
            EXEC sp_UpdateOrderStatus @OrderID=?, @NewStatus=?
        ''', order_id, 'Cancelled')
        
        # Gửi email thông báo hủy đơn hàng
        cursor.execute('SELECT Email, FullName FROM Customers WHERE CustomerID = ?', session['user_id'])
        customer = cursor.fetchone()
        
        if customer:
            html_content = f'''
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background-color: #ff6b6b; color: white; padding: 10px 20px; text-align: center; }}
                        .content {{ padding: 20px; border: 1px solid #ddd; }}
                        .footer {{ margin-top: 20px; font-size: 12px; color: #777; text-align: center; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Thông báo hủy đơn hàng</h2>
                        </div>
                        <div class="content">
                            <p>Xin chào {customer.FullName},</p>
                            <p>Đơn hàng #{order_id} của bạn đã được hủy theo yêu cầu.</p>
                            <p>Nếu bạn có bất kỳ câu hỏi nào, vui lòng liên hệ với chúng tôi.</p>
                        </div>
                        <div class="footer">
                            <p>© 2025 Fashion Store. All rights reserved.</p>
                        </div>
                    </div>
                </body>
                </html>
            '''
            send_email(customer.Email, 'Hủy đơn hàng - Fashion Store', html_content)
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã hủy đơn hàng thành công'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()