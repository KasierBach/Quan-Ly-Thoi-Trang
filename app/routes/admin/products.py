from flask import render_template, request, redirect, url_for, flash
import psycopg2
from app.database import get_db_connection
from app.services.product_service import ProductService
from app.services.attribute_service import AttributeService
from .blueprint import admin_bp, admin_required

@admin_bp.route('/admin/products')
@admin_required
def admin_products():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    sort_by = request.args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [12, 24, 48]: per_page = 12

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Sorting logic
    sort_query = "p.ProductID DESC"
    if sort_by == 'price_asc': sort_query = "p.Price ASC"
    elif sort_by == 'price_desc': sort_query = "p.Price DESC"
    elif sort_by == 'name_asc': sort_query = "p.ProductName ASC"
    
    # Count total records
    cursor.execute("SELECT COUNT(*) FROM Products")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * per_page
    
    cursor.execute(f'''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY {sort_query}
        LIMIT %s OFFSET %s
    ''', (per_page, offset))
    products = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('products.html', products=products, paging=paging_data, sort=sort_by)

@admin_bp.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        original_price = request.form.get('original_price', 0, type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Vui lòng điền đầy đủ thông tin', 'error')
            return redirect(url_for('admin.admin_add_product'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT sp_AddProduct(%s, %s, %s, %s, %s) AS ProductID', (product_name, description, price, category_id, original_price))
            result = cursor.fetchone()
            product_id = result.ProductID
            conn.commit()
            flash('Thêm sản phẩm thành công!', 'success')
            return redirect(url_for('admin.admin_edit_product', product_id=product_id))
        except psycopg2.Error as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
            return redirect(url_for('admin.admin_add_product'))
        finally:
            conn.close()
            
    return render_template('admin/add_product.html')

@admin_bp.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        original_price = request.form.get('original_price', 0, type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Thiếu thông tin', 'error')
            return redirect(url_for('admin.admin_edit_product', product_id=product_id))
        
        image_url = request.form.get('image_url', '').strip()
        result = ProductService.update_product(product_id, product_name, description, price, category_id, original_price, image_url)
        if result['success']:
            flash('Cập nhật thành công!', 'success')
        else:
            flash(f'Lỗi: {result["message"]}', 'error')
    
    cursor.execute('''
        SELECT p.*, c.CategoryName FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID WHERE p.ProductID = %s
    ''', (product_id,))
    product = cursor.fetchone()
    
    if not product:
        conn.close()
        flash('Sản phẩm không tồn tại', 'error')
        return redirect(url_for('admin.admin_products'))
    
    conn.close()
    
    variants = ProductService.get_product_variants(product_id)
    colors = ProductService.get_all_colors()
    sizes = ProductService.get_all_sizes()
    
    return render_template('admin/edit_product.html', product=product, variants=variants, colors=colors, sizes=sizes)

@admin_bp.route('/admin/products/add_variant', methods=['POST'])
@admin_required
def admin_add_variant():
    product_id = request.form.get('product_id', type=int)
    color_id = request.form.get('color_id', type=int)
    size_id = request.form.get('size_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if not product_id or not color_id or not size_id or not quantity:
        flash('Thiếu thông tin biến thể', 'error')
        return redirect(url_for('admin.admin_edit_product', product_id=product_id))
    
    result = ProductService.add_variant(product_id, color_id, size_id, quantity)
    if result['success']:
        flash('Thêm biến thể thành công!', 'success')
    else:
        flash(f'Lỗi: {result["message"]}', 'error')
    return redirect(url_for('admin.admin_edit_product', product_id=product_id))

@admin_bp.route('/admin/products/manage', methods=['GET', 'POST'])
@admin_required
def admin_manage_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        product_name = request.form.get('product_name')
        description = request.form.get('description')
        price = request.form.get('price', type=float)
        original_price = request.form.get('original_price', 0, type=float)
        category_id = request.form.get('category_id', type=int)
        
        if not product_name or not price or not category_id:
            flash('Vui lòng điền thông tin', 'error')
            conn.close()
            return redirect(url_for('admin.admin_manage_products'))
        
        try:
            cursor.execute('SELECT sp_AddProduct(%s, %s, %s, %s, %s) AS ProductID', (product_name, description, price, category_id, original_price))
            conn.commit()
            flash('Thêm thành công', 'success')
        except Exception as e:
            conn.rollback()
            flash(str(e), 'error')
        conn.close()
        return redirect(url_for('admin.admin_manage_products'))
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'newest')
    
    if page < 1: page = 1
    if per_page not in [10, 20, 50, 100]: per_page = 20
    
    sort_query = "p.ProductID DESC"
    if sort_by == 'price_asc': sort_query = "p.Price ASC"
    elif sort_by == 'price_desc': sort_query = "p.Price DESC"
    elif sort_by == 'name_asc': sort_query = "p.ProductName ASC"
    
    cursor.execute("SELECT COUNT(*) FROM Products")
    total_records = cursor.fetchone()[0]
    
    total_pages = (total_records + per_page - 1) // per_page if total_records > 0 else 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * per_page
    
    cursor.execute(f'''
        SELECT p.*, c.CategoryName,
        (SELECT COUNT(*) FROM ProductVariants WHERE ProductID = p.ProductID) AS VariantCount,
        (SELECT SUM(Quantity) FROM ProductVariants WHERE ProductID = p.ProductID) AS TotalStock
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        ORDER BY {sort_query}
        LIMIT %s OFFSET %s
    ''', (per_page, offset))
    
    products = cursor.fetchall()
    cursor.execute('SELECT * FROM Categories')
    categories = cursor.fetchall()
    conn.close()
    
    paging_data = {
        'total_records': total_records,
        'total_pages': total_pages,
        'current_page': page,
        'per_page': per_page,
        'start_index': offset + 1 if total_records > 0 else 0,
        'end_index': min(offset + per_page, total_records)
    }
    
    return render_template('admin/manage_products.html', products=products, categories=categories, paging=paging_data, sort_by=sort_by)

@admin_bp.route('/admin/attributes')
@admin_required
def admin_attributes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Colors ORDER BY ColorName')
    colors = cursor.fetchall()
    cursor.execute('SELECT * FROM Sizes ORDER BY SizeName')
    sizes = cursor.fetchall()
    conn.close()
    return render_template('admin/attributes.html', colors=colors, sizes=sizes)

@admin_bp.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM ProductVariants WHERE ProductID = %s', (product_id,))
        cursor.execute('DELETE FROM Products WHERE ProductID = %s', (product_id,))
        conn.commit()
        flash('Xóa thành công', 'success')
    except Exception as e:
        conn.rollback()
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('admin.admin_manage_products'))

@admin_bp.route('/admin/colors/add', methods=['POST'])
@admin_required
def admin_add_color():
    color_name = request.form.get('color_name')
    if not color_name: return redirect(request.referrer)
    
    result = AttributeService.add_color(color_name)
    if result['success']:
        flash('Thêm màu thành công', 'success')
    else:
        flash(f'Lỗi: {result["message"]}', 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/sizes/add', methods=['POST'])
@admin_required
def admin_add_size():
    size_name = request.form.get('size_name')
    if not size_name: return redirect(request.referrer)
    
    result = AttributeService.add_size(size_name)
    if result['success']:
        flash('Thêm kích thước thành công', 'success')
    else:
        flash(f'Lỗi: {result["message"]}', 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/variants/delete/<int:variant_id>', methods=['POST'])
@admin_required
def admin_delete_variant(variant_id):
    result = ProductService.delete_variant(variant_id)
    if result['success']:
        flash('Đã xóa biến thể thành công', 'success')
    else:
        flash(f'Lỗi: {result["message"]}', 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/colors/delete/<int:color_id>', methods=['POST'])
@admin_required
def admin_delete_color(color_id):
    result = AttributeService.delete_color(color_id)
    if result['success']:
        flash('Đã xóa màu thành công', 'success')
    else:
        flash(f'Lỗi: {result["message"]}', 'error')
    return redirect(request.referrer)

@admin_bp.route('/admin/sizes/delete/<int:size_id>', methods=['POST'])
@admin_required
def admin_delete_size(size_id):
    result = AttributeService.delete_size(size_id)
    if result['success']:
        flash('Đã xóa kích thước thành công', 'success')
    else:
        flash(f'Lỗi: {result["message"]}', 'error')
    return redirect(request.referrer)
