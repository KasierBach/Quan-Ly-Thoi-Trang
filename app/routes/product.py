from flask import Blueprint, abort, jsonify, render_template, request, session

from app.decorators import handle_db_errors, login_required
from app.services.feedback_service import FeedbackService
from app.services.product_service import ProductService
from app.services.wishlist_service import WishlistService
from app.validation import ValidationError, money, positive_int, required_text

product_bp = Blueprint('product', __name__)


def _payload():
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError('Dữ liệu không hợp lệ')
        return data
    return request.form


def _optional_id(args, name, label):
    value = args.get(name)
    return positive_int(value, label, ProductService.MAX_INTEGER) if value not in (None, '') else None


def _json_result(result):
    result = dict(result)
    status = result.pop('status_code', 200 if result.get('success') else 400)
    return jsonify(result), status


@product_bp.route('/products')
@handle_db_errors
def products():
    args = request.args
    try:
        category_id = _optional_id(args, 'category', 'Danh mục')
        color_id = _optional_id(args, 'color', 'Màu sắc')
        size_id = _optional_id(args, 'size', 'Kích thước')
        search_term = ProductService.optional_text(args.get('search', ''), 'Tìm kiếm', 200)
        min_price = money(args['min_price'], 'Giá tối thiểu') if args.get('min_price') else None
        max_price = money(args['max_price'], 'Giá tối đa') if args.get('max_price') else None
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValidationError('Giá tối thiểu không được lớn hơn giá tối đa')
        stock_filter = args.get('in_stock', '0')
        if stock_filter not in ('0', '1'):
            raise ValidationError('Bộ lọc tồn kho không hợp lệ')
        in_stock_only = int(stock_filter)
    except ValidationError as exc:
        return str(exc), 400
    try:
        page = positive_int(args.get('page', '1'), 'Trang', ProductService.MAX_INTEGER)
    except ValidationError:
        page = 1
    try:
        per_page = positive_int(args.get('per_page', '12'), 'Số sản phẩm mỗi trang')
    except ValidationError:
        per_page = 12
    if per_page not in (12, 24, 48):
        per_page = 12
    sort = args.get('sort', 'newest')
    if sort not in ProductService.SORTS:
        sort = 'newest'
    search_result = ProductService.search_products(
        search_term,
        category_id,
        min_price,
        max_price,
        color_id,
        size_id,
        in_stock_only,
        page,
        per_page,
        sort,
    )
    paging_data = {
        'total_records': search_result['total_records'],
        'total_pages': search_result['total_pages'],
        'current_page': search_result['current_page'],
        'per_page': per_page,
        'start_index': search_result['offset'] + 1 if search_result['total_records'] else 0,
        'end_index': min(search_result['offset'] + per_page, search_result['total_records']),
    }
    return render_template(
        'products.html',
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
        sort=sort,
    )


@product_bp.route('/api/search_autocomplete')
@handle_db_errors
def search_autocomplete():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify(success=True, products=[])
    query = required_text(query, 'Tìm kiếm', 200)
    return jsonify(success=True, products=ProductService.search_autocomplete(query))


@product_bp.route('/product/<int:product_id>')
@handle_db_errors
def product_detail(product_id):
    product_id = positive_int(product_id, 'Sản phẩm', ProductService.MAX_INTEGER)
    product = ProductService.get_product_by_id(product_id)
    if not product:
        abort(404)
    recent = session.get('recently_viewed', [])
    if not isinstance(recent, list):
        recent = []
    viewed = [product_id] + [pid for pid in recent if type(pid) is int and pid > 0 and pid != product_id][:9]
    if session.get('recently_viewed') != viewed:
        session['recently_viewed'] = viewed
    colors, sizes, variants_map = {}, {}, {}
    for variant in ProductService.get_product_variants(product_id):
        colors.setdefault(variant.ColorID, {'id': variant.ColorID, 'name': variant.ColorName})
        sizes.setdefault(variant.SizeID, {'id': variant.SizeID, 'name': variant.SizeName})
        variants_map[f'{variant.ColorID}_{variant.SizeID}'] = {
            'variant_id': variant.VariantID,
            'quantity': variant.Quantity,
        }
    return render_template(
        'product_detail.html',
        product=product,
        colors=list(colors.values()),
        sizes=list(sizes.values()),
        variants=variants_map,
    )


@product_bp.route('/api/get_variant', methods=['POST'])
@handle_db_errors
def get_variant():
    data = _payload()
    pid = positive_int(data.get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    cid = positive_int(data.get('color_id'), 'Màu sắc', ProductService.MAX_INTEGER)
    sid = positive_int(data.get('size_id'), 'Kích thước', ProductService.MAX_INTEGER)
    variant = ProductService.get_variant_by_details(pid, cid, sid)
    if not variant:
        return jsonify(success=False, message='Không tìm thấy biến thể'), 404
    return jsonify(success=True, variant_id=variant.VariantID, quantity=variant.Quantity)


@product_bp.route('/api/track_product_view', methods=['POST'])
@handle_db_errors
def track_product_view():
    pid = positive_int(_payload().get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    if not ProductService.get_product_by_id(pid):
        return jsonify(success=False, message='Sản phẩm không tồn tại'), 404
    recent = session.get('recently_viewed', [])
    if not isinstance(recent, list):
        recent = []
    ids = [pid]
    for value in recent:
        try:
            product_id = positive_int(value, 'Sản phẩm', ProductService.MAX_INTEGER)
        except ValidationError:
            continue
        if product_id not in ids:
            ids.append(product_id)
    if session.get('recently_viewed') != ids[:10]:
        session['recently_viewed'] = ids[:10]
    return jsonify(success=True)


@product_bp.route('/api/get_product_reviews')
@handle_db_errors
def get_product_reviews():
    pid = positive_int(request.args.get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    return _json_result(FeedbackService.get_product_reviews(pid))


@product_bp.route('/add_review', methods=['POST'])
@login_required
@handle_db_errors
def add_review():
    data = _payload()
    pid = positive_int(data.get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    rating = positive_int(data.get('rating'), 'Số sao', 5)
    comment = required_text(data.get('comment'), 'Nhận xét', 5000)
    return _json_result(FeedbackService.add_review(session['user_id'], pid, rating, comment))


@product_bp.route('/add_comment', methods=['POST'])
@login_required
@handle_db_errors
def add_comment():
    data = _payload()
    pid = positive_int(data.get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    content = required_text(data.get('content'), 'Bình luận', 5000)
    return _json_result(FeedbackService.add_comment(session['user_id'], pid, content))


@product_bp.route('/api/get_product_comments')
@handle_db_errors
def get_product_comments():
    pid = positive_int(request.args.get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    return _json_result(FeedbackService.get_product_comments(pid))


@product_bp.route('/api/get_recently_viewed')
@handle_db_errors
def get_recently_viewed():
    return jsonify(
        success=True, products=ProductService.get_recently_viewed_products(session.get('recently_viewed', []))
    )


@product_bp.route('/add_to_wishlist', methods=['POST'])
@login_required
@handle_db_errors
def add_to_wishlist():
    pid = positive_int(_payload().get('product_id'), 'Sản phẩm', ProductService.MAX_INTEGER)
    return _json_result(WishlistService.add_to_wishlist(session['user_id'], pid))


@product_bp.route('/wishlist')
@login_required
@handle_db_errors
def view_wishlist():
    return render_template('wishlist.html', wishlist_items=WishlistService.get_wishlist_by_user(session['user_id']))


@product_bp.route('/remove_from_wishlist', methods=['POST'])
@login_required
@handle_db_errors
def remove_from_wishlist():
    wid = positive_int(_payload().get('wishlist_id'), 'Danh sách yêu thích', ProductService.MAX_INTEGER)
    return _json_result(WishlistService.remove_from_wishlist(session['user_id'], wid))
