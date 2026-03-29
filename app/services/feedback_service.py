from app.services.base_service import BaseService
from datetime import datetime

class FeedbackService(BaseService):
    @staticmethod
    def add_review(user_id, product_id, rating, comment):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT ReviewID FROM Reviews WHERE CustomerID = %s AND ProductID = %s', (user_id, product_id))
                existing = cursor.fetchone()
                
                if existing:
                    cursor.execute('UPDATE Reviews SET Rating = %s, Comment = %s, ReviewDate = CURRENT_TIMESTAMP WHERE CustomerID = %s AND ProductID = %s', 
                                   (rating, comment, user_id, product_id))
                    msg = 'Đã cập nhật đánh giá của bạn'
                else:
                    cursor.execute('INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)', 
                                   (user_id, product_id, rating, comment))
                    msg = 'Cảm ơn bạn đã đánh giá sản phẩm'
                
                conn.commit()
                cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s', (user_id,))
                customer = cursor.fetchone()
                
                return {
                    'success': True, 'message': msg,
                    'review': {'customer_name': customer.FullName, 'rating': rating, 'comment': comment, 'date': datetime.now().strftime('%d/%m/%Y')}
                }
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def get_product_reviews(product_id):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT r.ReviewID, r.Rating, r.Comment, r.ReviewDate, c.FullName AS CustomerName
                    FROM Reviews r JOIN Customers c ON r.CustomerID = c.CustomerID
                    WHERE r.ProductID = %s ORDER BY r.ReviewDate DESC
                ''', (product_id,))
                reviews_data = cursor.fetchall()
                
                cursor.execute('SELECT AVG(CAST(Rating AS FLOAT)) AS AverageRating, COUNT(*) AS TotalReviews FROM Reviews WHERE ProductID = %s', (product_id,))
                avg_data = cursor.fetchone()
                
                cursor.execute('SELECT Rating, COUNT(*) as Count FROM Reviews WHERE ProductID = %s GROUP BY Rating', (product_id,))
                breakdown = {i: 0 for i in range(1, 6)}
                for row in cursor.fetchall():
                    try: breakdown[int(row.Rating)] = row.Count
                    except: continue

                return {
                    'success': True,
                    'reviews': [{'review_id': r.ReviewID, 'rating': r.Rating, 'comment': r.Comment, 'review_date': r.ReviewDate.strftime('%d/%m/%Y'), 'customer_name': r.CustomerName} for r in reviews_data],
                    'average_rating': float(avg_data.AverageRating or 0),
                    'total_reviews': int(avg_data.TotalReviews or 0),
                    'rating_breakdown': breakdown
                }
        except Exception as e:
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def add_comment(user_id, product_id, content):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, IsVisible) VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE)', 
                               (user_id, product_id, content))
                conn.commit()
                cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s', (user_id,))
                return {
                    'success': True, 'message': 'Cảm ơn bạn đã bình luận',
                    'comment': {'customer_name': cursor.fetchone().FullName, 'content': content, 'comment_date': datetime.now().strftime('%d/%m/%Y %H:%M')}
                }
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def get_product_comments(product_id):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, c.FullName AS CustomerName
                    FROM ProductComments pc JOIN Customers c ON pc.CustomerID = c.CustomerID
                    WHERE pc.ProductID = %s AND pc.IsVisible = TRUE ORDER BY pc.CommentDate DESC
                ''', (product_id,))
                return {
                    'success': True,
                    'comments': [{
                        'comment_id': c.CommentID, 'content': c.Content, 'comment_date': c.CommentDate.strftime('%d/%m/%Y %H:%M'),
                        'customer_name': c.CustomerName, 'reply': c.AdminReply, 'reply_date': c.ReplyDate.strftime('%d/%m/%Y %H:%M') if c.ReplyDate else None
                    } for c in cursor.fetchall()]
                }
        except Exception as e:
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def get_admin_comments(filter_type='', page=1, per_page=15):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                base_query = 'FROM ProductComments pc JOIN Customers c ON pc.CustomerID = c.CustomerID JOIN Products p ON pc.ProductID = p.ProductID'
                where = ""
                if filter_type == 'no_reply': where = " WHERE pc.AdminReply IS NULL"
                elif filter_type == 'replied': where = " WHERE pc.AdminReply IS NOT NULL"
                
                cursor.execute(f"SELECT COUNT(*) {base_query} {where}")
                total = cursor.fetchone()[0]
                total_pages = (total + per_page - 1) // per_page if total > 0 else 1
                page = min(max(1, page), total_pages)
                offset = (page - 1) * per_page
                
                cursor.execute(f'''
                    SELECT pc.*, c.FullName AS CustomerName, p.ProductName, p.ProductID
                    {base_query} {where} ORDER BY pc.CommentDate DESC LIMIT %s OFFSET %s
                ''', (per_page, offset))
                
                return {
                    'comments': cursor.fetchall(), 'total_records': total, 'total_pages': total_pages,
                    'current_page': page, 'per_page': per_page,
                    'start_index': offset + 1 if total > 0 else 0, 'end_index': min(offset + per_page, total)
                }
        finally:
            conn.close()

    @staticmethod
    def admin_reply_comment(comment_id, reply):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE ProductComments SET AdminReply = %s, ReplyDate = CURRENT_TIMESTAMP WHERE CommentID = %s', (reply, comment_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()

    @staticmethod
    def toggle_comment_visibility(comment_id, visible):
        conn = BaseService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE ProductComments SET IsVisible = %s WHERE CommentID = %s', (bool(visible), comment_id))
                conn.commit()
                return {'success': True}
        except Exception as e:
            conn.rollback()
            return BaseService.handle_error(e)
        finally:
            conn.close()
