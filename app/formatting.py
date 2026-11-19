from decimal import Decimal


def format_money(value):
    amount = Decimal(str(value or 0))
    return format(amount, ',.2f').rstrip('0').rstrip('.')
