from decimal import Decimal

import pytest

from app.formatting import format_money
from app.validation import ValidationError, positive_int


@pytest.mark.parametrize(
    'amount,expected',
    [('199000', '199,000'), ('199000.10', '199,000.1'), ('0.01', '0.01'), (Decimal('123.45'), '123.45'), (0, '0')],
)
def test_money_format_does_not_round_recorded_cents(amount, expected):
    assert format_money(amount) == expected


def test_huge_integer_input_is_a_validation_error():
    with pytest.raises(ValidationError):
        positive_int('9' * 5000, 'Số lượng')
