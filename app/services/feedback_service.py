from app.validation import ValidationError, positive_int, required_text

from .base_service import BaseService


class FeedbackService(BaseService):
    """Star reviews and discussion comments are separate persisted entities."""

    @staticmethod
    def _ids(user_id, product_id):
        return (
            positive_int(user_id, 'Khách hàng', max_value=2147483647),
            positive_int(product_id, 'Sản phẩm', max_value=2147483647),
        )

    @staticmethod
    def _target_customer(cursor, user_id, product_id):
        # Serialize a customer's review upserts and guard deletes during this write.
        cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s FOR UPDATE', (user_id,))
        customer = cursor.fetchone()
        if not customer:
            return None, {'success': False, 'message': 'Khách hàng không tồn tại', 'status_code': 404}
        cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s FOR KEY SHARE', (product_id,))
        if not cursor.fetchone():
            return None, {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
        return customer, None

    @staticmethod
    def _failure(exc):
        result = FeedbackService.handle_error(exc)
        result['status_code'] = 500
        return result

    @staticmethod
    def add_review(user_id, product_id, rating, comment):
        user_id, product_id = FeedbackService._ids(user_id, product_id)
        rating = positive_int(rating, 'Số sao', max_value=5)
        comment = required_text(comment, 'Nội dung đánh giá', 5000)
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                customer, error = FeedbackService._target_customer(cursor, user_id, product_id)
                if error or customer is None:
                    conn.rollback()
                    return error or {'success': False, 'message': 'Khách hàng không tồn tại', 'status_code': 404}
                cursor.execute(
                    'SELECT ReviewID FROM Reviews WHERE CustomerID = %s AND ProductID = %s', (user_id, product_id)
                )
                if cursor.fetchone():
                    cursor.execute(
                        """
                        UPDATE Reviews SET Rating = %s, Comment = %s, ReviewDate = CURRENT_TIMESTAMP
                        WHERE CustomerID = %s AND ProductID = %s RETURNING ReviewDate
                    """,
                        (rating, comment, user_id, product_id),
                    )
                    message = 'Đã cập nhật đánh giá của bạn'
                else:
                    cursor.execute(
                        """
                        INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING ReviewDate
                    """,
                        (user_id, product_id, rating, comment),
                    )
                    message = 'Cảm ơn bạn đã đánh giá sản phẩm'
                review_date = cursor.fetchone().ReviewDate
                conn.commit()
                return {
                    'success': True,
                    'message': message,
                    'review': {
                        'customer_name': customer.FullName,
                        'rating': rating,
                        'comment': comment,
                        'date': review_date.strftime('%d/%m/%Y'),
                    },
                }
        except Exception as exc:
            conn.rollback()
            return FeedbackService._failure(exc)
        finally:
            conn.close()

    @staticmethod
    def get_product_reviews(product_id):
        product_id = positive_int(product_id, 'Sản phẩm', max_value=2147483647)
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s', (product_id,))
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
                cursor.execute(
                    """
                    SELECT r.ReviewID, r.Rating, r.Comment, r.ReviewDate, c.FullName AS CustomerName
                    FROM Reviews r JOIN Customers c ON c.CustomerID = r.CustomerID
                    WHERE r.ProductID = %s ORDER BY r.ReviewDate DESC, r.ReviewID DESC
                """,
                    (product_id,),
                )
                reviews = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT AVG(CAST(Rating AS NUMERIC)) AS AverageRating, COUNT(*) AS TotalReviews
                    FROM Reviews WHERE ProductID = %s
                """,
                    (product_id,),
                )
                average = cursor.fetchone()
                cursor.execute(
                    'SELECT Rating, COUNT(*) AS Count FROM Reviews WHERE ProductID = %s GROUP BY Rating', (product_id,)
                )
                breakdown = {rating: 0 for rating in range(1, 6)}
                for row in cursor.fetchall():
                    if row.Rating in breakdown:
                        breakdown[int(row.Rating)] = int(row.Count)
                return {
                    'success': True,
                    'reviews': [
                        {
                            'review_id': row.ReviewID,
                            'rating': row.Rating,
                            'comment': row.Comment,
                            'review_date': row.ReviewDate.strftime('%d/%m/%Y') if row.ReviewDate else '',
                            'customer_name': row.CustomerName,
                        }
                        for row in reviews
                    ],
                    'average_rating': float(average.AverageRating or 0),
                    'total_reviews': int(average.TotalReviews or 0),
                    'rating_breakdown': breakdown,
                }
        except Exception as exc:
            return FeedbackService._failure(exc)
        finally:
            conn.close()

    @staticmethod
    def add_comment(user_id, product_id, content):
        user_id, product_id = FeedbackService._ids(user_id, product_id)
        content = required_text(content, 'Nội dung bình luận', 5000)
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                customer, error = FeedbackService._target_customer(cursor, user_id, product_id)
                if error or customer is None:
                    conn.rollback()
                    return error or {'success': False, 'message': 'Khách hàng không tồn tại', 'status_code': 404}
                cursor.execute(
                    """
                    INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, IsVisible)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE) RETURNING CommentDate
                """,
                    (user_id, product_id, content),
                )
                comment_date = cursor.fetchone().CommentDate
                conn.commit()
                return {
                    'success': True,
                    'message': 'Cảm ơn bạn đã bình luận',
                    'comment': {
                        'customer_name': customer.FullName,
                        'content': content,
                        'comment_date': comment_date.strftime('%d/%m/%Y %H:%M'),
                    },
                }
        except Exception as exc:
            conn.rollback()
            return FeedbackService._failure(exc)
        finally:
            conn.close()

    @staticmethod
    def get_product_comments(product_id):
        product_id = positive_int(product_id, 'Sản phẩm', max_value=2147483647)
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ProductID FROM Products WHERE ProductID = %s', (product_id,))
                if not cursor.fetchone():
                    return {'success': False, 'message': 'Sản phẩm không tồn tại', 'status_code': 404}
                cursor.execute(
                    """
                    SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate,
                           c.FullName AS CustomerName
                    FROM ProductComments pc JOIN Customers c ON c.CustomerID = pc.CustomerID
                    WHERE pc.ProductID = %s AND pc.IsVisible = TRUE
                    ORDER BY pc.CommentDate DESC, pc.CommentID DESC
                """,
                    (product_id,),
                )
                return {
                    'success': True,
                    'comments': [
                        {
                            'comment_id': row.CommentID,
                            'content': row.Content,
                            'comment_date': row.CommentDate.strftime('%d/%m/%Y %H:%M') if row.CommentDate else '',
                            'customer_name': row.CustomerName,
                            'reply': row.AdminReply,
                            'reply_date': row.ReplyDate.strftime('%d/%m/%Y %H:%M') if row.ReplyDate else None,
                        }
                        for row in cursor.fetchall()
                    ],
                }
        except Exception as exc:
            return FeedbackService._failure(exc)
        finally:
            conn.close()

    @staticmethod
    def get_admin_comments(filter_type='', page=1, per_page=15):
        if filter_type not in {'', 'no_reply', 'replied'}:
            raise ValidationError('Bộ lọc bình luận không hợp lệ')
        page = positive_int(page, 'Trang', max_value=1000000)
        per_page = positive_int(per_page, 'Số dòng', max_value=100)
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                base = (
                    'FROM ProductComments pc JOIN Customers c ON c.CustomerID = pc.CustomerID '
                    'JOIN Products p ON p.ProductID = pc.ProductID'
                )
                where = ''
                if filter_type == 'no_reply':
                    where = " WHERE NULLIF(BTRIM(pc.AdminReply), '') IS NULL"
                elif filter_type == 'replied':
                    where = " WHERE NULLIF(BTRIM(pc.AdminReply), '') IS NOT NULL"
                cursor.execute(f'SELECT COUNT(*) {base}{where}')
                total = cursor.fetchone()[0]
                total_pages = max(1, (total + per_page - 1) // per_page)
                page = min(page, total_pages)
                offset = (page - 1) * per_page
                cursor.execute(
                    f"""
                    SELECT pc.CommentID, pc.ProductID, pc.CustomerID, pc.Content, pc.CommentDate,
                           pc.AdminReply, pc.ReplyDate, pc.IsVisible, c.FullName AS CustomerName, p.ProductName
                    {base}{where} ORDER BY pc.CommentDate DESC, pc.CommentID DESC LIMIT %s OFFSET %s
                """,
                    (per_page, offset),
                )
                return {
                    'comments': cursor.fetchall(),
                    'total_records': total,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'start_index': offset + 1 if total else 0,
                    'end_index': min(offset + per_page, total),
                }
        finally:
            conn.close()

    @staticmethod
    def admin_reply_comment(comment_id, reply):
        comment_id = positive_int(comment_id, 'Bình luận', max_value=2147483647)
        reply = required_text(reply, 'Phản hồi', 5000)
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ProductComments SET AdminReply = %s, ReplyDate = CURRENT_TIMESTAMP
                    WHERE CommentID = %s RETURNING CommentID, ReplyDate
                """,
                    (reply, comment_id),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    return {'success': False, 'message': 'Bình luận không tồn tại', 'status_code': 404}
                conn.commit()
                return {
                    'success': True,
                    'message': 'Đã lưu phản hồi bình luận',
                    'reply': reply,
                    'reply_date': row.ReplyDate.strftime('%d/%m/%Y %H:%M'),
                }
        except Exception as exc:
            conn.rollback()
            return FeedbackService._failure(exc)
        finally:
            conn.close()

    @staticmethod
    def toggle_comment_visibility(comment_id, visible):
        comment_id = positive_int(comment_id, 'Bình luận', max_value=2147483647)
        if type(visible) is bool:
            enabled = visible
        elif type(visible) is int and visible in (0, 1):
            enabled = visible == 1
        elif type(visible) is str and visible in ('0', '1'):
            enabled = visible == '1'
        else:
            raise ValidationError('Trạng thái hiển thị không hợp lệ')
        conn = FeedbackService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ProductComments SET IsVisible = %s WHERE CommentID = %s RETURNING CommentID
                """,
                    (enabled, comment_id),
                )
                if not cursor.fetchone():
                    conn.rollback()
                    return {'success': False, 'message': 'Bình luận không tồn tại', 'status_code': 404}
                conn.commit()
                return {'success': True, 'message': 'Đã cập nhật hiển thị bình luận', 'visible': enabled}
        except Exception as exc:
            conn.rollback()
            return FeedbackService._failure(exc)
        finally:
            conn.close()
