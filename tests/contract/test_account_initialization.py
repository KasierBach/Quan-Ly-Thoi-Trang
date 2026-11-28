"""Account markup must initialize after Bootstrap and use unique address anchors."""

from bs4 import BeautifulSoup

from app.database import CaseInsensitiveRecord
from app.services.auth_service import AuthService
from app.services.order_service import OrderService


def test_account_uses_unique_address_id_and_deferred_bootstrap_init(auth_client, monkeypatch):
    monkeypatch.setattr(
        AuthService,
        'get_customer_profile',
        lambda uid: CaseInsensitiveRecord(CustomerID=uid, FullName='Synthetic Customer', DarkModeEnabled=False),
    )
    monkeypatch.setattr(
        OrderService, 'get_customer_orders', lambda *_: {'orders': [], 'total_orders': 0, 'total_spent': 0}
    )
    response = auth_client.get('/my_account')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    ids = [element['id'] for element in soup.select('[id]')]
    assert len(ids) == len(set(ids))
    assert soup.select_one('div#address') is not None
    assert soup.select_one('textarea#shippingAddress')['name'] == 'address'
    assert soup.select_one('label[for="shippingAddress"]').get_text() == 'Địa chỉ giao hàng mặc định'
    account = next(script.get_text() for script in soup.find_all('script') if 'account-config' in script.get_text())
    assert "document.addEventListener('DOMContentLoaded'" in account
    assert 'bootstrap.Tab.getOrCreateInstance(target).show()' in account
