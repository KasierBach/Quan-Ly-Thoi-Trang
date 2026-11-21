from datetime import datetime

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, url_for

from app.decorators import handle_db_errors
from app.seo import (
    PRIVATE_PATHS,
    default_metadata,
    metadata_response_headers,
    public_base_url,
    public_url,
    sitemap_document,
)
from app.services.main_service import MainService
from app.services.product_service import ProductService
from app.validation import ValidationError, email_address


main_bp = Blueprint('main', __name__)
main_bp.app_context_processor(default_metadata)
main_bp.after_app_request(metadata_response_headers)


@main_bp.route('/robots.txt')
def robots_txt():
    # No templates, categories, or database reads are needed for this endpoint.
    lines = ['User-agent: *', 'Allow: /'] + [f'Disallow: {path}' for path in PRIVATE_PATHS]
    sitemap_url = public_url('main.sitemap_xml')
    if sitemap_url:
        lines.extend(['', f'Sitemap: {sitemap_url}'])
    response = Response('\n'.join(lines) + '\n', content_type='text/plain; charset=utf-8')
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


@main_bp.route('/sitemap.xml')
def sitemap_xml():
    base = public_base_url()
    try:
        if not base:
            raise ValueError('Public base URL is not configured')
        if request.args:
            return Response('Unsupported sitemap query.\n', status=400, content_type='text/plain; charset=utf-8')
        body = sitemap_document(base, ProductService.get_sitemap_entries())
    except Exception as exc:
        current_app.logger.warning('Public sitemap unavailable (%s)', type(exc).__name__)
        response = Response('Sitemap temporarily unavailable.\n', status=503, content_type='text/plain; charset=utf-8')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Retry-After'] = '300'
        return response
    response = Response(body, content_type='application/xml; charset=utf-8')
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


@main_bp.route('/')
@handle_db_errors
def home():
    featured = ProductService.get_featured_products(8)
    best_selling = ProductService.get_best_selling_products(8)
    return render_template('index.html', featured_products=featured, best_selling=best_selling)


def _contact_page(values=None, error=None):
    return render_template(
        'contact.html',
        values=values or {},
        error=error,
        contact_address=current_app.config.get('CONTACT_ADDRESS'),
        contact_phone=current_app.config.get('CONTACT_PHONE'),
        contact_email=current_app.config.get('CONTACT_EMAIL'),
    )


@main_bp.route('/contact', methods=['GET', 'POST'])
@handle_db_errors
def contact():
    if request.method == 'GET':
        return _contact_page()
    values = {field: request.form.get(field, '') for field in ('name', 'email', 'subject', 'message')}
    try:
        validated = MainService.validate_contact(values['name'], values['email'], values['subject'], values['message'])
        result = MainService.add_contact_message(*validated)
    except ValidationError as exc:
        return _contact_page(values, str(exc)), 400
    if not result['success']:
        return _contact_page(values, 'Gửi tin không thành công. Vui lòng thử lại sau.'), 500
    flash('Đã lưu tin nhắn liên hệ. Cảm ơn bạn!', 'success')
    return redirect(url_for('main.contact'))


@main_bp.route('/subscribe_newsletter', methods=['POST'])
@handle_db_errors
def subscribe_newsletter():
    try:
        email = email_address(request.form.get('email'))
        result = dict(MainService.subscribe_newsletter(email))
    except ValidationError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    status = result.pop('status_code', 200 if result.get('success') else 500)
    return jsonify(result), status


@main_bp.route('/health/live')
def health_live():
    return jsonify({'status': 'live'}), 200


@main_bp.route('/health/ready')
@main_bp.route('/health')
def health_check():
    is_healthy = MainService.check_health()
    return jsonify(
        {
            'status': 'healthy' if is_healthy else 'unhealthy',
            'database': 'connected' if is_healthy else 'error',
            'timestamp': datetime.now().isoformat(),
        }
    ), (200 if is_healthy else 503)
