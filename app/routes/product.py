from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.database import get_db_connection
import psycopg2
from datetime import datetime
import decimal
from app.services.product_service import ProductService
from app.services.wishlist_service import WishlistService
from app.services.feedback_service import FeedbackService

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
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    sort = request.args.get('sort', 'newest')
    
    if page < 1: page = 1
    if per_page not in [12, 24, 48]: per_page = 12 # Common values for 3-4 column grid

    colors = ProductService.get_all_colors()
    sizes = ProductService.get_all_sizes()
    
    # Search via Service
    search_result = ProductService.search_products(
        search_term, category_id, min_price, max_price, 
        color_id, size_id, in_stock_only, page, per_page, sort
    )
    products = search_result['products']
    
    paging_data = {
        'total_records': search_result['total_records'],
        'total_pages': search_result['total_pages'],
        'current_page': search_result['current_page'],
        'per_page': per_page,
        'start_index': search_result['offset'] + 1 if search_result['total_records'] > 0 else 0,
        'end_index': min(search_result['offset'] + per_page, search_result['total_records'])
    }
    

    
    return render_template('products.html', 
                          products=products, 
                          colors=colors,
                          sizes=sizes,
                          current_category=category_id,
                          search_term=search_term,
                          min_price=min_price,
                          max_price=max_price,
                          color_id=color_id,
                          size_id=size_id,
                          in_stock_only=in_stock_only,
                          paging=paging_data,
                          sort=sort)

@product_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = ProductService.get_product_by_id(product_id)
    
    if not product:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('product.products'))
    
    variants = ProductService.get_product_variants(product_id)
    
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
    

    
    # Get rating stats from FeedbackService
    feedback_data = FeedbackService.get_product_reviews(product_id)
    rating_breakdown = feedback_data.get('rating_breakdown', {1:0, 2:0, 3:0, 4:0, 5:0})
    average_rating = feedback_data.get('average_rating', 0)
    total_reviews = feedback_data.get('total_reviews', 0)

    return render_template('product_detail.html',
                          product=product,
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
    
    variant = ProductService.get_variant_by_details(product_id, color_id, size_id)
    
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
    
    result = FeedbackService.add_review(session['user_id'], product_id, rating, comment)
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result) # Propagate failure message

@product_bp.route('/add_comment', methods=['POST'])
def add_comment():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để bình luận sản phẩm'})
    
    product_id = request.form.get('product_id', type=int)
    content = request.form.get('content')
    
    if not product_id or not content:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    result = FeedbackService.add_comment(session['user_id'], product_id, content)
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result)

@product_bp.route('/api/get_product_comments', methods=['GET'])
def get_product_comments():
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID required'})
    
    result = FeedbackService.get_product_comments(product_id)
    return jsonify(result)

@product_bp.route('/api/get_product_reviews', methods=['GET'])
def get_product_reviews():
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID required'})
    
    result = FeedbackService.get_product_reviews(product_id)
    return jsonify(result)

@product_bp.route('/api/search_autocomplete')
def search_autocomplete():
    """API endpoint for live search autocomplete"""
    query = request.args.get('q', '').strip()
    if len(query) < 1:
        return jsonify({'success': True, 'products': []})
    
    products = ProductService.search_autocomplete(query, limit=8)
    return jsonify({'success': True, 'products': products})

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
    
    success, message = WishlistService.add_to_wishlist(session['user_id'], product_id)
    return jsonify({'success': success, 'message': message})

@product_bp.route('/wishlist')
def view_wishlist():
    if 'user_id' not in session:
        return redirect(url_for('auth.login', next=url_for('product.view_wishlist')))
    
    wishlist_items = WishlistService.get_wishlist_by_user(session['user_id'])
    
    return render_template('wishlist.html', wishlist_items=wishlist_items)

@product_bp.route('/remove_from_wishlist', methods=['POST'])
def remove_from_wishlist():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập'})
    
    wishlist_id = request.form.get('wishlist_id', type=int)
    if not wishlist_id:
        return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    success, message = WishlistService.remove_from_wishlist(session['user_id'], wishlist_id)
    return jsonify({'success': success, 'message': message})
