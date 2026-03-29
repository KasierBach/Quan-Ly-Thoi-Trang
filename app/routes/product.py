from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.product_service import ProductService
from app.services.wishlist_service import WishlistService
from app.services.feedback_service import FeedbackService
from app.decorators import handle_db_errors

product_bp = Blueprint('product', __name__)

@product_bp.route('/products')
@handle_db_errors
def products():
    args = request.args
    category_id = args.get('category', type=int)
    search_term = args.get('search', '')
    min_price, max_price = args.get('min_price', type=float), args.get('max_price', type=float)
    color_id, size_id = args.get('color', type=int), args.get('size', type=int)
    in_stock_only = args.get('in_stock', type=int, default=0)
    page, per_page = args.get('page', 1, type=int), args.get('per_page', 12, type=int)
    sort = args.get('sort', 'newest')
    
    if page < 1: page = 1
    if per_page not in [12, 24, 48]: per_page = 12

    search_result = ProductService.search_products(
        search_term, category_id, min_price, max_price, 
        color_id, size_id, in_stock_only, page, per_page, sort
    )
    
    paging_data = {
        'total_records': search_result['total_records'],
        'total_pages': search_result['total_pages'],
        'current_page': search_result['current_page'],
        'per_page': per_page,
        'start_index': search_result['offset'] + 1 if search_result['total_records'] > 0 else 0,
        'end_index': min(search_result['offset'] + per_page, search_result['total_records'])
    }
    
    return render_template('products.html', 
                          products=search_result['products'], 
                          colors=ProductService.get_all_colors(),
                          sizes=ProductService.get_all_sizes(),
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
@handle_db_errors
def product_detail(product_id):
    product = ProductService.get_product_by_id(product_id)
    if not product:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('product.products'))
    
    variants = ProductService.get_product_variants(product_id)
    colors, sizes, variants_map = {}, {}, {}
    
    for v in variants:
        if v.ColorID not in colors: colors[v.ColorID] = {'id': v.ColorID, 'name': v.ColorName}
        if v.SizeID not in sizes: sizes[v.SizeID] = {'id': v.SizeID, 'name': v.SizeName}
        variants_map[f"{v.ColorID}_{v.SizeID}"] = {'variant_id': v.VariantID, 'quantity': v.Quantity}
    
    feedback_data = FeedbackService.get_product_reviews(product_id)
    return render_template('product_detail.html',
                          product=product,
                          colors=list(colors.values()),
                          sizes=list(sizes.values()),
                          variants=variants_map,
                          rating_breakdown=feedback_data.get('rating_breakdown', {1:0,2:0,3:0,4:0,5:0}),
                          average_rating=float(feedback_data.get('average_rating', 0)),
                          total_reviews=int(feedback_data.get('total_reviews', 0)))

@product_bp.route('/api/get_variant', methods=['POST'])
@handle_db_errors
def get_variant():
    pid, cid, sid = request.form.get('product_id', type=int), request.form.get('color_id', type=int), request.form.get('size_id', type=int)
    if not all([pid, cid, sid]): return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    v = ProductService.get_variant_by_details(pid, cid, sid)
    if not v: return jsonify({'success': False, 'message': 'Không tìm thấy biến thể'})
    
    return jsonify({'success': True, 'variant_id': v.VariantID, 'quantity': v.Quantity})

@product_bp.route('/add_review', methods=['POST'])
@login_required
@handle_db_errors
def add_review():
    uid = session['user_id']
    pid, rating, comment = request.form.get('product_id', type=int), request.form.get('rating', type=int), request.form.get('comment')
    if not pid or not (1 <= (rating or 0) <= 5): return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    return jsonify(FeedbackService.add_review(uid, pid, rating, comment))

@product_bp.route('/api/get_recently_viewed')
@handle_db_errors
def get_recently_viewed():
    rv = session.get('recently_viewed', [])
    if not rv: return jsonify({'success': True, 'products': []})
    
    return jsonify({'success': True, 'products': ProductService.get_recently_viewed_products(rv)})

@product_bp.route('/add_to_wishlist', methods=['POST'])
@login_required
@handle_db_errors
def add_to_wishlist():
    uid = session['user_id']
    
    pid = (request.get_json() if request.is_json else request.form).get('product_id')
    try: pid = int(pid)
    except: pid = None
    
    if not pid: return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    success, message = WishlistService.add_to_wishlist(uid, pid)
    return jsonify({'success': success, 'message': message})

@product_bp.route('/wishlist')
@login_required
@handle_db_errors
def view_wishlist():
    uid = session['user_id']
    return render_template('wishlist.html', wishlist_items=WishlistService.get_wishlist_by_user(uid))

@product_bp.route('/remove_from_wishlist', methods=['POST'])
@login_required
@handle_db_errors
def remove_from_wishlist():
    uid = session['user_id']
    
    wid = request.form.get('wishlist_id', type=int)
    if not wid: return jsonify({'success': False, 'message': 'Dữ liệu không hợp lệ'})
    
    success, message = WishlistService.remove_from_wishlist(uid, wid)
    return jsonify({'success': success, 'message': message})
