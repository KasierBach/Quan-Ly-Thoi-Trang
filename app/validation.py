from datetime import date
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit, urlunsplit


PHONE_NUMBER_FORMAT_MESSAGE = 'Số điện thoại cần từ 8 đến 15 chữ số, có thể bắt đầu bằng +'


class ValidationError(ValueError):
    pass


def required_text(value, field, max_length):
    if not isinstance(value, str):
        raise ValidationError(f'{field} không hợp lệ')
    value = value.strip()
    if not value or len(value) > max_length or '\x00' in value:
        raise ValidationError(f'{field} không hợp lệ')
    return value


def positive_int(value, field, max_value=None):
    text = str(value)
    if isinstance(value, bool) or len(text) > 20 or not re.fullmatch(r'[0-9]+', text):
        raise ValidationError(f'{field} phải là số nguyên dương')
    result = int(text)
    if result < 1 or (max_value is not None and result > max_value):
        raise ValidationError(f'{field} không hợp lệ')
    return result


def email_address(value):
    value = required_text(value, 'Email', 254).casefold()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise ValidationError('Email không hợp lệ')
    return value


def money(value, field):
    if isinstance(value, bool):
        raise ValidationError(f'{field} không hợp lệ')
    text = str(value)
    if len(text) > 40:
        raise ValidationError(f'{field} không hợp lệ')
    try:
        amount = Decimal(text)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f'{field} không hợp lệ') from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal('9999999999999999.99'):
        raise ValidationError(f'{field} không hợp lệ')
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise ValidationError(f'{field} chỉ nhận tối đa hai chữ số thập phân')
    return amount.quantize(Decimal('0.01'))


def date_value(value, field):
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f'{field} không hợp lệ') from exc
    return result


def phone_number(value, optional=False):
    if optional and value in (None, ''):
        return None
    value = required_text(value, 'Số điện thoại', 20)
    if not re.fullmatch(r'\+?[0-9]{8,15}', value):
        raise ValidationError(PHONE_NUMBER_FORMAT_MESSAGE)
    return value


def password_value(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise ValidationError('Mật khẩu cần từ 8 đến 128 ký tự')
    if not (re.search(r'[a-z]', value) and re.search(r'[A-Z]', value) and re.search(r'\d', value)):
        raise ValidationError('Mật khẩu cần chữ hoa, chữ thường và số')
    return value


def local_redirect(value):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value) or '\\' in value:
        return None
    if not value.startswith('/') or value.startswith('//'):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    return urlunsplit(('', '', parsed.path, parsed.query, parsed.fragment))
