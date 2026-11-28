from typing import NamedTuple
from uuid import NAMESPACE_URL, uuid4, uuid5

from flask import current_app, request, session
from psycopg2.extras import Json

from app.services.base_service import BaseService
from app.services.product_service import ProductService


class CartSnapshot(NamedTuple):
    cart_id: str
    revision: str
    items: list
    persisted: bool


class CartService(BaseService):
    @staticmethod
    def load(cart_id):
        conn = CartService.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT replace(revision::text, '-', ''), items FROM ShoppingCarts WHERE cart_id = %s",
                    (cart_id,),
                )
                row = cursor.fetchone()
                return (row[0], row[1]) if row else None
        finally:
            conn.close()

    @staticmethod
    def replace(cart_id, expected_revision, items):
        revision = uuid4().hex
        conn = CartService.get_connection()
        try:
            with conn.cursor() as cursor:
                if expected_revision is None:
                    cursor.execute(
                        """INSERT INTO ShoppingCarts (cart_id, revision, items) VALUES (%s, %s, %s)
                           ON CONFLICT (cart_id) DO NOTHING""",
                        (cart_id, revision, Json(items)),
                    )
                else:
                    cursor.execute(
                        """UPDATE ShoppingCarts SET revision = %s, items = %s, updated_at = CURRENT_TIMESTAMP
                           WHERE cart_id = %s AND revision = %s""",
                        (revision, Json(items), cart_id, expected_revision),
                    )
                changed = cursor.rowcount == 1
                conn.commit()
                return changed
        finally:
            conn.close()


def previous_session_key(purpose):
    cookie = request.cookies.get(current_app.config['SESSION_COOKIE_NAME'], '')
    return uuid5(NAMESPACE_URL, f'fashion-store:{purpose}:{cookie}').hex


def ensure_cart_id():
    if 'cart_id' not in session:
        cookie = request.cookies.get(current_app.config['SESSION_COOKIE_NAME'])
        session['cart_id'] = previous_session_key('cart-id') if cookie else uuid4().hex
    return session['cart_id']


def current_cart():
    cart_id = ensure_cart_id()
    saved = CartService.load(cart_id)
    if saved:
        return CartSnapshot(cart_id, saved[0], saved[1], True)
    items = ProductService.normalize_cart_items(session.get('cart', []))
    revision = session.get('cart_revision') or previous_session_key('cart')
    if items and 'cart_revision' not in session:
        session['cart_revision'] = revision
    return CartSnapshot(cart_id, revision, items, False)


def replace_cart(snapshot, items):
    if CartService.replace(snapshot.cart_id, snapshot.revision if snapshot.persisted else None, items):
        session.pop('cart', None)
        session.pop('cart_revision', None)
        return True
    return False
