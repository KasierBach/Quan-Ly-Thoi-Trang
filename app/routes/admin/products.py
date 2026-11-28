from flask import abort, flash, redirect, render_template, request, session, url_for

from app.decorators import handle_db_errors
from app.services.attribute_service import AttributeService
from app.services.category_service import CategoryService
from app.services.media_service import MediaService
from app.services.product_service import ProductService
from app.validation import ValidationError, money, positive_int, required_text

from .blueprint import admin_bp, admin_required, paging_args


PRODUCT_SORTS = {'newest', 'price_asc', 'price_desc', 'name_asc'}
MAX_ID = 2147483647


def _product_fields():
    name = required_text(request.form.get('product_name'), 'Tên sản phẩm', 255)
    description = request.form.get('description', '')
    if description.strip():
        description = required_text(description, 'Mô tả', 10000)
    elif '\x00' in description:
        raise ValidationError('Mô tả không hợp lệ')
    else:
        description = ''
    price = money(request.form.get('price'), 'Giá bán')
    original_price = money(request.form.get('original_price') or '0', 'Giá gốc')
    if original_price and original_price < price:
        raise ValidationError('Giá gốc phải bằng hoặc cao hơn giá bán')
    category_id = positive_int(request.form.get('category_id'), 'Danh mục', MAX_ID)
    return name, description, price, category_id, original_price


def _product_paging(default=20, allowed=(10, 20, 50, 100)):
    page, per_page = paging_args(request.args, default=default, allowed=allowed)
    sort_by = request.args.get('sort_by', 'newest')
    if sort_by not in PRODUCT_SORTS:
        abort(400, description='Cách sắp xếp không hợp lệ')
    return page, per_page, sort_by


def _flash_result(result, success_message):
    flash(
        success_message if result['success'] else result.get('message', 'Không thể thực hiện thao tác'),
        'success' if result['success'] else 'error',
    )


@admin_bp.route('/admin/products')
@admin_required
@handle_db_errors
def admin_products():
    page, per_page, sort_by = _product_paging(default=12, allowed=(12, 10, 24, 20, 48, 50, 100))
    result = ProductService.get_admin_products(page, per_page, sort_by)
    return render_template('products.html', products=result['products'], paging=result, sort=sort_by)


@admin_bp.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
@handle_db_errors
def admin_add_product():
    if request.method == 'GET':
        return render_template('admin/add_product.html', categories=CategoryService.get_all_categories())
    try:
        result = ProductService.add_product(*_product_fields())
    except ValidationError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.admin_add_product'))
    if result['success']:
        flash('Thêm sản phẩm thành công!', 'success')
        return redirect(url_for('admin.admin_edit_product', product_id=result['product_id']))
    _flash_result(result, 'Thêm sản phẩm thành công!')
    return redirect(url_for('admin.admin_add_product'))


@admin_bp.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@admin_required
@handle_db_errors
def admin_edit_product(product_id):
    try:
        product_id = positive_int(product_id, 'Sản phẩm', MAX_ID)
    except ValidationError as exc:
        abort(400, description=str(exc))
    product = ProductService.get_product_by_id(product_id)
    if not product:
        abort(404)
    if request.method == 'POST':
        try:
            fields = _product_fields()
            image = request.form.get('image_url', '').strip()
            if image:
                image = required_text(image, 'Đường dẫn ảnh', 255)
            result = ProductService.update_product(product_id, *fields, image)
            _flash_result(result, 'Cập nhật thành công!')
        except ValidationError as exc:
            flash(str(exc), 'error')
        return redirect(url_for('admin.admin_edit_product', product_id=product_id))
    history_page, history_size = paging_args(request.args, allowed=(20,))
    return render_template(
        'admin/edit_product.html',
        product=product,
        inventory_history=ProductService.get_inventory_history(product_id, history_page, history_size),
        categories=CategoryService.get_all_categories(),
        variants=ProductService.get_product_variants(product_id),
        colors=AttributeService.get_all_colors(),
        sizes=AttributeService.get_all_sizes(),
        pixabay_enabled=MediaService.pixabay_enabled(),
    )


@admin_bp.route('/admin/products/add_variant', methods=['POST'])
@admin_required
@handle_db_errors
def admin_add_variant():
    product_id = None
    try:
        product_id = positive_int(request.form.get('product_id'), 'Sản phẩm', MAX_ID)
        color_id = positive_int(request.form.get('color_id'), 'Màu', MAX_ID)
        size_id = positive_int(request.form.get('size_id'), 'Kích thước', MAX_ID)
        raw_quantity = request.form.get('quantity')
        quantity = 0 if raw_quantity == '0' else positive_int(raw_quantity, 'Số lượng', MAX_ID)
        result = ProductService.add_variant(
            product_id, color_id, size_id, quantity, actor_id=session['user_id'], reason=request.form.get('reason')
        )
        _flash_result(result, 'Đã lưu biến thể và số lượng tồn kho.')
    except ValidationError as exc:
        flash(str(exc), 'error')
    if product_id is None:
        return redirect(url_for('admin.admin_manage_products'))
    return redirect(url_for('admin.admin_edit_product', product_id=product_id))


@admin_bp.route('/admin/products/<int:product_id>/variants/<int:variant_id>/stock', methods=['POST'])
@admin_required
@handle_db_errors
def admin_adjust_variant_stock(product_id, variant_id):
    result = ProductService.adjust_variant_stock(
        product_id,
        variant_id,
        request.form.get('delta'),
        actor_id=session['user_id'],
        reason=request.form.get('reason'),
    )
    _flash_result(result, f'Đã điều chỉnh tồn kho. Số lượng sau điều chỉnh là {result.get("quantity")}.')
    return redirect(url_for('admin.admin_edit_product', product_id=product_id))


@admin_bp.route('/admin/products/manage', methods=['GET', 'POST'])
@admin_required
@handle_db_errors
def admin_manage_products():
    if request.method == 'POST':
        try:
            _flash_result(ProductService.add_product(*_product_fields()), 'Thêm sản phẩm thành công!')
        except ValidationError as exc:
            flash(str(exc), 'error')
        return redirect(url_for('admin.admin_manage_products'))
    page, per_page, sort_by = _product_paging()
    result = ProductService.get_admin_products(page, per_page, sort_by)
    return render_template(
        'admin/manage_products.html',
        products=result['products'],
        categories=CategoryService.get_all_categories(),
        paging=result,
        sort_by=sort_by,
    )


@admin_bp.route('/admin/attributes')
@admin_required
@handle_db_errors
def admin_attributes():
    return render_template(
        'admin/attributes.html', colors=AttributeService.get_all_colors(), sizes=AttributeService.get_all_sizes()
    )


@admin_bp.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_product(product_id):
    try:
        product_id = positive_int(product_id, 'Sản phẩm', MAX_ID)
        _flash_result(ProductService.delete_product(product_id), 'Xóa sản phẩm thành công')
    except ValidationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin.admin_manage_products'))


@admin_bp.route('/admin/colors/add', methods=['POST'])
@admin_required
@handle_db_errors
def admin_add_color():
    try:
        _flash_result(AttributeService.add_color(request.form.get('color_name')), 'Thêm màu thành công')
    except ValidationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin.admin_attributes'))


@admin_bp.route('/admin/sizes/add', methods=['POST'])
@admin_required
@handle_db_errors
def admin_add_size():
    try:
        _flash_result(AttributeService.add_size(request.form.get('size_name')), 'Thêm kích thước thành công')
    except ValidationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin.admin_attributes'))


@admin_bp.route('/admin/variants/delete/<int:variant_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_variant(variant_id):
    try:
        variant_id = positive_int(variant_id, 'Biến thể', MAX_ID)
        _flash_result(ProductService.delete_variant(variant_id), 'Xóa biến thể thành công')
    except ValidationError as exc:
        flash(str(exc), 'error')
    # Never trust a caller-controlled Referrer for redirect destinations.
    product_id = request.form.get('product_id')
    try:
        product_id = positive_int(product_id, 'Sản phẩm', MAX_ID)
    except ValidationError:
        return redirect(url_for('admin.admin_manage_products'))
    return redirect(url_for('admin.admin_edit_product', product_id=product_id))


@admin_bp.route('/admin/colors/delete/<int:color_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_color(color_id):
    try:
        _flash_result(AttributeService.delete_color(color_id), 'Xóa màu thành công')
    except ValidationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin.admin_attributes'))


@admin_bp.route('/admin/sizes/delete/<int:size_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_size(size_id):
    try:
        _flash_result(AttributeService.delete_size(size_id), 'Xóa kích thước thành công')
    except ValidationError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('admin.admin_attributes'))
