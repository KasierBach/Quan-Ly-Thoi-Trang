from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.database import get_db_connection
import psycopg2
from datetime import datetime
import decimal

product_bp = Blueprint('product', __name__)

@product_bp.route('/products')
def products():
    category_id = request.args.get('category', type=int)
    search_term = request.args.get('search', '')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    color_id = request.args.get('color', type=int)
    size_id = request.args.get('size', type=int)
    in_stock_only = request.args.get('in_stock', type=int, default=0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    
    cursor.execute('SELECT * FROM Colors')
    colors = cursor.fetchall()
    
    cursor.execute('SELECT * FROM Sizes')
    sizes = cursor.fetchall()
    
    cursor.execute('''
        SELECT * FROM sp_SearchProducts(%s, %s, %s, %s, %s, %s, %s)
    ''', (search_term, category_id, min_price, max_price, color_id, size_id, bool(in_stock_only)))
    
    products = cursor.fetchall()
    conn.close()
    
    return render_template('products.html', 
                          products=products, 
                          categories=categories,
                          colors=colors,
                          sizes=sizes,
                          current_category=category_id,
                          search_term=search_term,
                          min_price=min_price,
                          max_price=max_price,
                          color_id=color_id,
                          size_id=size_id,
                          in_stock_only=in_stock_only)

@product_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT p.*, c.CategoryName 
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE p.ProductID = %s
    ''', (product_id,))
    product = cursor.fetchone()
    
    if not product:
        conn.close()
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('product.products'))
    
    cursor.execute('''
        SELECT pv.VariantID, c.ColorID, c.ColorName, s.SizeID, s.SizeName, pv.Quantity
        FROM ProductVariants pv
        JOIN Colors c ON pv.ColorID = c.ColorID
        JOIN Sizes s ON pv.SizeID = s.SizeID
        WHERE pv.ProductID = %s
    ''', (product_id,))
    variants = cursor.fetchall()
    
    colors = {}
    sizes = {}
    variants_map = {}
    
    for variant in variants:
        color_id = variant.ColorID
        size_id = variant.SizeID
        if color_id not in colors:
            colors[color_id] = {'id': color_id, 'name': variant.ColorName}
        if size_id not in sizes:
            sizes[size_id] = {'id': size_id, 'name': variant.SizeName}
        
        key = f"{color_id}_{size_id}"
        variants_map[key] = {'variant_id': variant.VariantID, 'quantity': variant.Quantity}
    
    cursor.execute("""
    SELECT Rating, COUNT(*) as Count
    FROM Reviews
    WHERE ProductID = %s
    GROUP BY Rating
    """, (product_id,))
    raw_breakdown = cursor.fetchall()

    rating_breakdown = {i: 0 for i in range(1, 6)}
    for row in raw_breakdown:
        try:
            rating = int(row[0])
            if 1 <= rating <= 5:
                rating_breakdown[rating] = row[1]
        except (ValueError, TypeError, KeyError):
            continue

    cursor.execute("""
    SELECT AVG(CAST(Rating AS FLOAT)) AS AverageRating, COUNT(*) AS TotalReviews
    FROM Reviews
    WHERE ProductID = %s
    """, (product_id,))
    rating_data = cursor.fetchone()
    average_rating = rating_data.AverageRating if rating_data and rating_data.AverageRating else 0
    total_reviews = rating_data.TotalReviews if rating_data else 0

    conn.close()

    return render_template('product_detail.html',
                          product=product,
                          original_price=float(product.Price * decimal.Decimal('1.2')),
                          colors=list(colors.values()),
                          sizes=list(sizes.values()),
                          variants=variants_map,
                          rating_breakdown=rating_breakdown,
                          average_rating=float(average_rating),
                          total_reviews=int(total_reviews))

@product_bp.route('/api/get_variant', methods=['POST'])
def get_variant():
    product_id = request.form.get('product_id', type=int)
    color_id = request.form.get('color_id', type=int)
    size_id = request.form.get('size_id', type=int)
    
    if not product_id or not color_id or not size_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT VariantID, Quantity 
        FROM ProductVariants 
        WHERE ProductID = %s AND ColorID = %s AND SizeID = %s
    ''', (product_id, color_id, size_id))
    variant = cursor.fetchone()
    conn.close()
    
    if not variant:
        return jsonify({'success': False, 'message': 'Không tìm thấy biến thể sản phẩm'})
    
    return jsonify({
        'success': True,
        'variant_id': variant.VariantID,
        'quantity': variant.Quantity
    })

@product_bp.route('/add_review', methods=['POST'])
def add_review():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để đánh giá sản phẩm'})
    
    product_id = request.form.get('product_id', type=int)
    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment')
    
    if not product_id or not rating or rating < 1 or rating > 5:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM Reviews 
            WHERE CustomerID = %s AND ProductID = %s
        ''', (session['user_id'], product_id))
        
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute('''
                UPDATE Reviews
                SET Rating = %s, Comment = %s, ReviewDate = CURRENT_TIMESTAMP
                WHERE CustomerID = %s AND ProductID = %s
            ''', (rating, comment, session['user_id'], product_id))
            message = 'Đã cập nhật đánh giá của bạn'
        else:
            cursor.execute('''
                INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ''', (session['user_id'], product_id, rating, comment))
            message = 'Cảm ơn bạn đã đánh giá sản phẩm'
        
        conn.commit()
        
        cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s', (session['user_id'],))
        customer = cursor.fetchone()
        
        return jsonify({
            'success': True, 
            'message': message,
            'review': {
                'customer_name': customer.FullName,
                'rating': rating,
                'comment': comment,
                'date': datetime.now().strftime('%d/%m/%Y')
            }
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@product_bp.route('/add_comment', methods=['POST'])
def add_comment():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để bình luận sản phẩm'})
    
    product_id = request.form.get('product_id', type=int)
    content = request.form.get('content')
    
    if not product_id or not content:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, IsVisible)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, TRUE)
        ''', (session['user_id'], product_id, content))
        conn.commit()
        
        cursor.execute('SELECT FullName FROM Customers WHERE CustomerID = %s', (session['user_id'],))
        customer = cursor.fetchone()
        
        return jsonify({
            'success': True, 
            'message': 'Cảm ơn bạn đã bình luận sản phẩm',
            'comment': {
                'customer_name': customer.FullName,
                'content': content,
                'comment_date': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Đã xảy ra lỗi: {str(e)}'})
    finally:
        conn.close()

@product_bp.route('/api/get_product_comments', methods=['GET'])
def get_product_comments():
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID required'})
    
    conn = get_db_connection()
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
        return jsonify({'success': True, 'comments': comments})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@product_bp.route('/api/get_product_reviews', methods=['GET'])
def get_product_reviews():
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID required'})
    
    conn = get_db_connection()
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
        
        cursor.execute('''
            SELECT AVG(CAST(Rating AS FLOAT)) AS AverageRating, COUNT(*) AS TotalReviews
            FROM Reviews
            WHERE ProductID = %s
        ''', (product_id,))
        avg_data = cursor.fetchone()
        average_rating = avg_data.AverageRating if avg_data and avg_data.AverageRating else 0
        total_reviews = avg_data.TotalReviews if avg_data else 0
        
        cursor.execute('''
            SELECT Rating, COUNT(*) as Count
            FROM Reviews
            WHERE ProductID = %s
            GROUP BY Rating
            ORDER BY Rating DESC
        ''', (product_id,))
        rating_breakdown_data = cursor.fetchall()
        rating_breakdown = {i: 0 for i in range(1, 6)}
        for row in rating_breakdown_data:
            try:
                rating = int(row.Rating)
                if 1 <= rating <= 5:
                    rating_breakdown[rating] = row.Count
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
        
        return jsonify({
            'success': True,
            'reviews': reviews,
            'average_rating': float(average_rating),
            'total_reviews': int(total_reviews),
            'rating_breakdown': rating_breakdown
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@product_bp.route('/api/track_product_view', methods=['POST'])
def track_product_view():
    product_id = request.form.get('product_id', type=int)
    if not product_id: return jsonify({'success': False})
    
    if 'recently_viewed' not in session: session['recently_viewed'] = []
    if product_id in session['recently_viewed']: session['recently_viewed'].remove(product_id)
    session['recently_viewed'].insert(0, product_id)
    session['recently_viewed'] = session['recently_viewed'][:5]
    session.modified = True
    return jsonify({'success': True})

@product_bp.route('/api/get_recently_viewed')
def get_recently_viewed():
    if 'recently_viewed' not in session or not session['recently_viewed']:
        return jsonify({'success': True, 'products': []})
    
    product_ids = session['recently_viewed']
    product_ids_str = ','.join(map(str, product_ids))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT p.ProductID, p.ProductName, p.Price, p.ImageURL, c.CategoryName
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE p.ProductID IN ({product_ids_str})
    ''')
    products = cursor.fetchall()
    conn.close()
    
    result = []
    for product_id in product_ids:
        for product in products:
            if product.ProductID == product_id:
                result.append({
                    'product_id': product.ProductID,
                    'product_name': product.ProductName,
                    'price': float(product.Price),
                    'image_url': product.ImageURL,
                    'category_name': product.CategoryName
                })
                break
    return jsonify({'success': True, 'products': result})

@product_bp.route('/add_to_wishlist', methods=['POST'])
def add_to_wishlist():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để sử dụng tính năng này'})
    
    if request.is_json:
        data = request.get_json()
        product_id = data.get('product_id', None)
    else:
        product_id = request.form.get('product_id', type=int)
    
    try: product_id = int(product_id)
    except: product_id = None
    
    if not product_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM Wishlist WHERE CustomerID = %s AND ProductID = %s', (session['user_id'], product_id))
        if cursor.fetchone():
            return jsonify({'success': True, 'message': 'Sản phẩm đã có trong danh sách yêu thích'})
        
        cursor.execute('INSERT INTO Wishlist (CustomerID, ProductID, AddedDate) VALUES (%s, %s, CURRENT_TIMESTAMP)', (session['user_id'], product_id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã thêm vào danh sách yêu thích'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    finally:
        conn.close()

@product_bp.route('/wishlist')
def view_wishlist():
    if 'user_id' not in session:
        return redirect(url_for('auth.login', next=url_for('product.view_wishlist')))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.WishlistID, p.ProductID, p.ProductName, p.Price, c.CategoryName,
          (SELECT ColorName FROM Colors cl JOIN ProductVariants pv ON cl.ColorID = pv.ColorID WHERE pv.ProductID = p.ProductID LIMIT 1) AS FirstColor,
          p.ImageURL, w.AddedDate
        FROM Wishlist w
        JOIN Products p ON w.ProductID = p.ProductID
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE w.CustomerID = %s
        ORDER BY w.AddedDate DESC
    ''', (session['user_id'],))
    wishlist_items = cursor.fetchall()
    
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    return render_template('wishlist.html', wishlist_items=wishlist_items, categories=categories)

@product_bp.route('/remove_from_wishlist', methods=['POST'])
def remove_from_wishlist():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập'})
    
    wishlist_id = request.form.get('wishlist_id', type=int)
    if not wishlist_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM Wishlist WHERE WishlistID = %s AND CustomerID = %s', (wishlist_id, session['user_id']))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Không có quyền thực hiện'})
        
        cursor.execute('DELETE FROM Wishlist WHERE WishlistID = %s', (wishlist_id,))
        conn.commit()
        return jsonify({'success': True, 'message': 'Đã xóa khỏi danh sách yêu thích'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'Lỗi: {str(e)}'})
    finally:
        conn.close()
