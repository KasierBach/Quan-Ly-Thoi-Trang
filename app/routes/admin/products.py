from flask import render_template, request, redirect, url_for, flash
from app.services.product_service import ProductService
from app.services.attribute_service import AttributeService
from .blueprint import admin_bp, admin_required
from app.decorators import handle_db_errors

@admin_bp.route('/admin/products')
@admin_required
@handle_db_errors
def admin_products():
    args = request.args
    page, per_page = args.get('page', 1, type=int), args.get('per_page', 12, type=int)
    sort_by = args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [12, 10, 24, 20, 48, 50, 100]: per_page = 20

    res = ProductService.get_admin_products(page, per_page, sort_by)
    return render_template('products.html', products=res['products'], paging=res, sort=sort_by)

@admin_bp.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
@handle_db_errors
def admin_add_product():
    if request.method == 'GET':
        return render_template('admin/add_product.html')
        
    name, price = request.form.get('product_name'), request.form.get('price', type=float)
    cid = request.form.get('category_id', type=int)
    desc, op = request.form.get('description'), request.form.get('original_price', 0, type=float)
    
    if not all([name, price, cid]):
        flash('Vui lòng điền đầy đủ thông tin', 'error')
        return redirect(url_for('admin.admin_add_product'))
    
    res = ProductService.add_product(name, desc, price, cid, op)
    if res['success']:
        flash('Thêm sản phẩm thành công!', 'success')
        return redirect(url_for('admin.admin_edit_product', product_id=res['product_id']))
    
    flash(res.get('message', 'Lỗi khi thêm sản phẩm'), 'error')
    return redirect(url_for('admin.admin_add_product'))

@admin_bp.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@admin_required
@handle_db_errors
def admin_edit_product(product_id):
    if request.method == 'POST':
        name, price = request.form.get('product_name'), request.form.get('price', type=float)
        cid = request.form.get('category_id', type=int)
        desc, op = request.form.get('description'), request.form.get('original_price', 0, type=float)
        img = request.form.get('image_url', '').strip()
        
        if not all([name, price, cid]):
            flash('Thiếu thông tin', 'error')
        else:
            res = ProductService.update_product(product_id, name, desc, price, cid, op, img)
            flash('Cập nhật thành công!' if res['success'] else res.get('message', 'Lỗi cập nhật'), 
                  'success' if res['success'] else 'error')
    
    product = ProductService.get_product_by_id(product_id)
    if not product:
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('admin.admin_products'))
    
    return render_template('admin/edit_product.html', 
                          product=product, variants=ProductService.get_product_variants(product_id), 
                          colors=ProductService.get_all_colors(), sizes=ProductService.get_all_sizes())

@admin_bp.route('/admin/products/add_variant', methods=['POST'])
@admin_required
@handle_db_errors
def admin_add_variant():
    pid, cid, sid = request.form.get('product_id', type=int), request.form.get('color_id', type=int), request.form.get('size_id', type=int)
    qty = request.form.get('quantity', type=int)
    
    if not all([pid, cid, sid, qty]):
        flash('Thiếu thông tin biến thể', 'error')
    else:
        res = ProductService.add_variant(pid, cid, sid, qty)
        flash('Thêm thành công!' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
        
    return redirect(url_for('admin.admin_edit_product', product_id=pid))

@admin_bp.route('/admin/products/manage', methods=['GET', 'POST'])
@admin_required
@handle_db_errors
def admin_manage_products():
    if request.method == 'POST':
        name, price = request.form.get('product_name'), request.form.get('price', type=float)
        cid = request.form.get('category_id', type=int)
        desc, op = request.form.get('description'), request.form.get('original_price', 0, type=float)
        
        if not all([name, price, cid]):
            flash('Vui lòng điền thông tin', 'error')
        else:
            res = ProductService.add_product(name, desc, price, cid, op)
            flash('Thêm thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
        return redirect(url_for('admin.admin_manage_products'))
    
    args = request.args
    page, per_page = args.get('page', 1, type=int), args.get('per_page', 20, type=int)
    sort_by = args.get('sort_by', 'newest')
    
    res = ProductService.get_admin_products(page, per_page, sort_by)
    from app.services.category_service import CategoryService
    return render_template('admin/manage_products.html', 
                          products=res['products'], categories=CategoryService.get_all_categories(), 
                          paging=res, sort_by=sort_by)

@admin_bp.route('/admin/attributes')
@admin_required
@handle_db_errors
def admin_attributes():
    return render_template('admin/attributes.html', 
                          colors=AttributeService.get_all_colors(), 
                          sizes=AttributeService.get_all_sizes())

@admin_bp.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_product(product_id):
    # ProductService should handle cascading if DB doesn't, but here we keep it simple
    res = ProductService.delete_product(product_id)
    flash('Xóa thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
    return redirect(url_for('admin.admin_manage_products'))

@admin_bp.route('/admin/colors/add', methods=['POST'])
@admin_required
@handle_db_errors
def admin_add_color():
    name = request.form.get('color_name')
    if name: 
        res = AttributeService.add_color(name)
        flash('Thêm thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/sizes/add', methods=['POST'])
@admin_required
@handle_db_errors
def admin_add_size():
    name = request.form.get('size_name')
    if name:
        res = AttributeService.add_size(name)
        flash('Thêm thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/variants/delete/<int:variant_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_variant(variant_id):
    res = ProductService.delete_variant(variant_id)
    flash('Đã xóa thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/colors/delete/<int:color_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_color(color_id):
    res = AttributeService.delete_color(color_id)
    flash('Đã xóa thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/sizes/delete/<int:size_id>', methods=['POST'])
@admin_required
@handle_db_errors
def admin_delete_size(size_id):
    res = AttributeService.delete_size(size_id)
    flash('Đã xóa thành công' if res['success'] else res.get('message', 'Lỗi'), 'success' if res['success'] else 'error')
    return redirect(request.referrer)
