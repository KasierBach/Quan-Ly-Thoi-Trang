from app.services.base_service import BaseService
from datetime import datetime

class FeedbackService(BaseService):
    @staticmethod
    def add_review(user_id, product_id, rating, comment):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            # Check existing review
            cursor.execute('SELECT ReviewID FROM Reviews WHERE CustomerID = %s AND ProductID = %s', (user_id, product_id))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute('''
                    UPDATE Reviews
                    SET Rating = %s, Comment = %s, ReviewDate = CURRENT_TIMESTAMP
                    WHERE CustomerID = %s AND ProductID = %s
                ''', (rating, comment, user_id, product_id))
                message = 'Đã cập nhật đánh giá của bạn'
            else:
                cursor.execute('''
                    INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ''', (user_id, product_id, rating, comment))
                message = 'Cảm ơn bạn đã đánh giá sản phẩm'
            
            conn.commit()
            
            # Get customer name for response
            cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s', (user_id,))
            customer = cursor.fetchone()
            
            return {
                'success': True,
                'message': message,
                'review': {
                    'customer_name': customer.FullName,
                    'rating': rating,
                    'comment': comment,
                    'date': datetime.now().strftime('%d/%m/%Y')
                }
            }
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_product_reviews(product_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT r.ReviewID, r.Rating, r.Comment, r.ReviewDate, c.FullName AS CustomerName
                FROM Reviews r
                JOIN Customers c ON r.CustomerID = c.CustomerID
                WHERE r.ProductID = %s
                ORDER BY r.ReviewDate DESC
            ''', (product_id,))
            reviews_data = cursor.fetchall()
            
            # Helper for stats
            cursor.execute('''
                SELECT AVG(CAST(Rating AS FLOAT)) AS AverageRating, COUNT(*) AS TotalReviews
                FROM Reviews WHERE ProductID = %s
            ''', (product_id,))
            avg_data = cursor.fetchone()
            average_rating = avg_data.AverageRating if avg_data and avg_data.AverageRating else 0
            total_reviews = avg_data.TotalReviews if avg_data else 0
            
            cursor.execute('''
                SELECT Rating, COUNT(*) as Count FROM Reviews
                WHERE ProductID = %s GROUP BY Rating
            ''', (product_id,))
            rating_breakdown_data = cursor.fetchall()
            rating_breakdown = {i: 0 for i in range(1, 6)}
            for row in rating_breakdown_data:
                try:
                    r = int(row.Rating)
                    if 1 <= r <= 5: rating_breakdown[r] = row.Count
                except: continue

            reviews = []
            for review in reviews_data:
                reviews.append({
                    'review_id': review.ReviewID,
                    'rating': review.Rating,
                    'comment': review.Comment,
                    'review_date': review.ReviewDate.strftime('%d/%m/%Y'),
                    'customer_name': review.CustomerName
                })
                
            return {
                'success': True,
                'reviews': reviews,
                'average_rating': float(average_rating),
                'total_reviews': int(total_reviews),
                'rating_breakdown': rating_breakdown
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_comment(user_id, product_id, content):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, IsVisible)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE)
            ''', (user_id, product_id, content))
            conn.commit()
            
            cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s', (user_id,))
            customer = cursor.fetchone()
            
            return {
                'success': True,
                'message': 'Cảm ơn bạn đã bình luận sản phẩm',
                'comment': {
                    'customer_name': customer.FullName,
                    'content': content,
                    'comment_date': datetime.now().strftime('%d/%m/%Y %H:%M')
                }
            }
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_product_comments(product_id):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT pc.CommentID, pc.Content, pc.CommentDate, pc.AdminReply, pc.ReplyDate, 
                       c.FullName AS CustomerName
                FROM ProductComments pc
                JOIN Customers c ON pc.CustomerID = c.CustomerID
                WHERE pc.ProductID = %s AND pc.IsVisible = TRUE
                ORDER BY pc.CommentDate DESC
            ''', (product_id,))
            comments_data = cursor.fetchall()
            
            comments = []
            for comment in comments_data:
                comments.append({
                    'comment_id': comment.CommentID,
                    'content': comment.Content,
                    'comment_date': comment.CommentDate.strftime('%d/%m/%Y %H:%M'),
                    'customer_name': comment.CustomerName,
                    'reply': comment.AdminReply,
                    'reply_date': comment.ReplyDate.strftime('%d/%m/%Y %H:%M') if comment.ReplyDate else None
                })
            return {'success': True, 'comments': comments}
        except Exception as e:
            return {'success': False, 'message': str(e)}
        finally:
            cursor.close()
            conn.close()
