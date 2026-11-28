"""The reconstructed main schema is a complete, additive PostgreSQL contract."""

import hashlib
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql
import pytest


pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]

EXPECTED_COLUMNS = {
    'categories': {'categoryid', 'categoryname', 'description'},
    'customers': {
        'customerid',
        'fullname',
        'email',
        'password',
        'phonenumber',
        'address',
        'isadmin',
        'darkmodeenabled',
        'createdat',
        'gender',
        'dateofbirth',
        'avatar_url',
        'bio',
        'last_seen',
        'role',
        'auth_version',
    },
    'products': {
        'productid',
        'productname',
        'description',
        'price',
        'originalprice',
        'categoryid',
        'imageurl',
        'createdat',
    },
    'colors': {'colorid', 'colorname'},
    'sizes': {'sizeid', 'sizename'},
    'productvariants': {'variantid', 'productid', 'colorid', 'sizeid', 'quantity'},
    'inventoryadjustments': {
        'id', 'product_id', 'variant_id', 'color_name', 'size_name', 'actor_id', 'actor_name',
        'reason', 'quantity_before', 'quantity_after', 'created_at',
    },
    'orders': {
        'orderid',
        'customerid',
        'orderdate',
        'totalamount',
        'status',
        'paymentmethod',
        'shippingaddress',
        'recipient_name',
        'recipient_phone',
        'recipient_email',
        'notes',
        'checkout_key',
    },
    'orderdetails': {'orderdetailid', 'orderid', 'variantid', 'quantity', 'price'},
    'wishlist': {'wishlistid', 'customerid', 'productid', 'addeddate'},
    'reviews': {'reviewid', 'customerid', 'productid', 'rating', 'comment', 'reviewdate'},
    'contactmessages': {'messageid', 'name', 'email', 'subject', 'message', 'submitdate', 'status'},
    'newslettersubscribers': {'subscriberid', 'email', 'subscribedate', 'isactive'},
    'productcomments': {
        'commentid',
        'customerid',
        'productid',
        'content',
        'commentdate',
        'adminreply',
        'replydate',
        'isvisible',
    },
    'passwordresettokens': {'tokenid', 'customerid', 'token', 'expirydate', 'isused', 'createdat'},
    'messages': {
        'id',
        'sender_type',
        'content',
        'session_id',
        'user_id',
        'is_read',
        'created_at',
        'conversation_id',
        'message_type',
        'reply_to_id',
        'is_deleted',
        'deleted_at',
        'edited_at',
    },
    'conversations': {
        'id',
        'type',
        'name',
        'avatar_url',
        'created_by',
        'created_at',
        'updated_at',
        'theme_color',
        'default_emoji',
    },
    'participants': {'id', 'conversation_id', 'user_id', 'role', 'nickname', 'is_muted', 'joined_at', 'last_read_at'},
    'attachments': {
        'id',
        'message_id',
        'file_url',
        'file_name',
        'file_type',
        'mime_type',
        'file_size',
        'thumbnail_url',
        'width',
        'height',
        'duration',
        'created_at',
        'storage_name',
    },
    'reactions': {'id', 'message_id', 'user_id', 'emoji', 'created_at'},
    'pinnedmessages': {'id', 'conversation_id', 'message_id', 'pinned_by', 'pinned_at'},
}


@pytest.fixture
def schema_sandbox(db_connection):
    """Fresh/legacy bootstrap proof with transactional DDL; no schema DROP/reset."""
    name = 'test_schema_' + uuid4().hex
    with db_connection.cursor() as cursor:
        cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    yield name
    db_connection.rollback()


def _transactional_sql(path, schema='public'):
    # Remove only the outer transaction commands, retaining every PL/pgSQL BEGIN.
    content = path.read_text(encoding='utf-8')
    content = content.replace('BEGIN;\nSET LOCAL', 'SET LOCAL', 1).removesuffix('COMMIT;\n')
    return content.replace('search_path = public,', f'search_path = {schema},').replace('public.', f'{schema}.')


def _install(connection, schema):
    with connection.cursor() as cursor:
        cursor.execute(_transactional_sql(ROOT / 'db' / 'bootstrap.sql', schema))


def _columns(connection, schema):
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT table_name, column_name FROM information_schema.columns
                          WHERE table_schema = %s AND table_name = ANY(%s)""",
            (schema, list(EXPECTED_COLUMNS)),
        )
        result = {table: set() for table in EXPECTED_COLUMNS}
        for row in cursor.fetchall():
            result[row.table_name].add(row.column_name)
        return result


def _snapshot(connection, schema='public'):
    with connection.cursor() as cursor:
        result = {}
        for table in EXPECTED_COLUMNS:
            cursor.execute(
                sql.SQL(
                    'SELECT to_jsonb(row_data) AS item FROM {}.{} AS row_data ORDER BY to_jsonb(row_data)::text'
                ).format(sql.Identifier(schema), sql.Identifier(table))
            )
            result[table] = [row.item for row in cursor.fetchall()]
        return result


def _reject(connection, statement, parameters=(), code='23514'):
    with connection.cursor() as cursor:
        cursor.execute('SAVEPOINT expected_constraint')
        with pytest.raises(psycopg2.Error) as raised:
            if parameters:
                cursor.execute(statement, parameters)
            else:
                cursor.execute(statement)
        cursor.execute('ROLLBACK TO SAVEPOINT expected_constraint')
        cursor.execute('RELEASE SAVEPOINT expected_constraint')
    assert raised.value.pgcode == code


def test_bootstrap_installs_every_main_sql_column_on_empty_schema(db_connection, schema_sandbox):
    _install(db_connection, schema_sandbox)
    assert _columns(db_connection, schema_sandbox) == EXPECTED_COLUMNS
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM Customers')
        assert cursor.fetchone()[0] == 0
        cursor.execute('SELECT COUNT(*) FROM Orders')
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            """SELECT COUNT(*) FROM pg_trigger WHERE NOT tgisinternal
                          AND tgrelid IN (%s::regclass, %s::regclass, %s::regclass)""",
            (f'{schema_sandbox}.customers', f'{schema_sandbox}.orders', f'{schema_sandbox}.orderdetails'),
        )
        assert cursor.fetchone()[0] == 4


def test_bootstrap_adds_missing_january_customer_fields_without_changing_rows(db_connection, schema_sandbox):
    with db_connection.cursor() as cursor:
        cursor.execute(sql.SQL('SET LOCAL search_path = {}, pg_catalog').format(sql.Identifier(schema_sandbox)))
        cursor.execute("""CREATE TABLE Customers (
            CustomerID SERIAL PRIMARY KEY, FullName VARCHAR(255) NOT NULL,
            Email VARCHAR(255) NOT NULL UNIQUE, Password VARCHAR(255) NOT NULL,
            PhoneNumber VARCHAR(20) UNIQUE, Address VARCHAR(500), IsAdmin BOOLEAN DEFAULT FALSE,
            DarkModeEnabled BOOLEAN DEFAULT FALSE, CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""INSERT INTO Customers
            (FullName, Email, Password, Address, CreatedAt) VALUES
            ('Legacy Synthetic', 'legacy@example.test', 'synthetic-hash-not-a-real-user',
             'Legacy Synthetic Street', TIMESTAMP '2026-01-01') RETURNING *""")
        old = dict(cursor.fetchone())
    _install(db_connection, schema_sandbox)
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT * FROM Customers')
        actual = cursor.fetchone()
        assert {key: actual[key] for key in old} == old
        assert actual.auth_version == 1
        assert actual.role == 'customer'
        assert actual.avatar_url is None
        assert actual.Gender is None
        assert actual.DateOfBirth is None
    assert _columns(db_connection, schema_sandbox) == EXPECTED_COLUMNS


@pytest.mark.parametrize('token_type', ['UUID NOT NULL DEFAULT gen_random_uuid()', 'VARCHAR(100) NOT NULL'])
def test_password_reset_migration_retires_plaintext_and_preserves_digests(db_connection, schema_sandbox, token_type):
    legacy = str(uuid4())
    current = hashlib.sha256(b'existing-reset-link').hexdigest()
    with db_connection.cursor() as cursor:
        cursor.execute(sql.SQL('SET LOCAL search_path = {}, pg_catalog').format(sql.Identifier(schema_sandbox)))
        cursor.execute(
            sql.SQL(
                'CREATE TABLE PasswordResetTokens (TokenID SERIAL PRIMARY KEY, CustomerID INT NOT NULL, '
                'Token {}, ExpiryDate TIMESTAMP NOT NULL, IsUsed BOOLEAN DEFAULT FALSE, '
                'CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'
            ).format(sql.SQL(token_type))
        )
        cursor.execute(
            'INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate) '
            "VALUES (1, %s, CURRENT_TIMESTAMP + INTERVAL '1 hour')",
            (legacy,),
        )
        if token_type.startswith('VARCHAR'):
            cursor.execute(
                'INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate) '
                "VALUES (2, %s, CURRENT_TIMESTAMP + INTERVAL '1 hour')",
                (current,),
            )
    _install(db_connection, schema_sandbox)
    migration = _transactional_sql(ROOT / 'db/migrations/0005_password_reset_compat.sql', schema_sandbox)
    with db_connection.cursor() as cursor:
        cursor.execute(migration)
        cursor.execute(migration)
        cursor.execute('SELECT CustomerID, Token, IsUsed FROM PasswordResetTokens ORDER BY TokenID')
        previous = [(row.CustomerID, row.Token, row.IsUsed) for row in cursor.fetchall()]
        expected = [(1, hashlib.sha256(f'retired-reset-token:{legacy}'.encode()).hexdigest(), True)]
        if token_type.startswith('VARCHAR'):
            expected.append((2, current, False))
        assert previous == expected
        cursor.execute(
            'SELECT convalidated FROM pg_constraint '
            "WHERE conrelid = 'passwordresettokens'::regclass AND conname = 'passwordresettokens_sha256'"
        )
        assert cursor.fetchone().convalidated is True
        cursor.execute(
            'INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate) '
            "VALUES (3, %s, CURRENT_TIMESTAMP + INTERVAL '1 hour') RETURNING Token",
            ('a' * 64,),
        )
        assert cursor.fetchone().Token == 'a' * 64


def test_bootstrap_replay_preserves_seeded_data_and_trigger_count(db_connection):
    before = _snapshot(db_connection)
    with db_connection.cursor() as cursor:
        cursor.execute((ROOT / 'db' / 'bootstrap.sql').read_text(encoding='utf-8'))
    assert _snapshot(db_connection) == before
    with db_connection.cursor() as cursor:
        cursor.execute("""SELECT COUNT(*) FROM pg_trigger WHERE NOT tgisinternal
                          AND tgrelid IN ('public.customers'::regclass, 'public.orders'::regclass,
                                          'public.orderdetails'::regclass)""")
        assert cursor.fetchone()[0] == 4


def test_seed_replay_neither_replenishes_stock_nor_creates_duplicate_chat(db_connection):
    before = _snapshot(db_connection)
    with db_connection.cursor() as cursor:
        cursor.execute((ROOT / 'db' / 'seed_test.sql').read_text(encoding='utf-8'))
    assert _snapshot(db_connection) == before


def test_seed_requires_explicit_validated_loopback_setting(db_connection):
    before = _snapshot(db_connection)
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT set_config('thua2.allow_test_seed', '', true)")
    _reject(db_connection, _transactional_sql(ROOT / 'db' / 'seed_test.sql'), code='P0001')
    assert _snapshot(db_connection) == before


def test_seed_refuses_reserved_ids_with_nonfixture_data(db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute("UPDATE Customers SET Email = 'not-a-fixture@example.test' WHERE CustomerID = 1")
    before = _snapshot(db_connection)
    _reject(db_connection, _transactional_sql(ROOT / 'db' / 'seed_test.sql'), code='P0001')
    assert _snapshot(db_connection) == before


def test_auth_profile_chat_alias_column_and_reset_digest_contract(db_connection):
    assert _columns(db_connection, 'public') == EXPECTED_COLUMNS
    with db_connection.cursor() as cursor:
        cursor.execute("""UPDATE Customers SET Gender = 'other', DateOfBirth = DATE '1995-02-03',
                          avatar_url = '/static/images/default.jpg' WHERE CustomerID = 1""")
        cursor.execute("""SELECT Gender, DateOfBirth, avatar_url AS AvatarUrl,
                                 auth_version AS AuthVersion FROM Customers WHERE CustomerID = 1""")
        row = cursor.fetchone()
        assert row.Gender == 'other'
        assert row.DateOfBirth.isoformat() == '1995-02-03'
        assert row.AvatarUrl == '/static/images/default.jpg'
        assert row.AuthVersion == 1
        digest = hashlib.sha256(b'synthetic-reset-token').hexdigest()
        cursor.execute(
            """INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate)
                          VALUES (1, %s, CURRENT_TIMESTAMP + INTERVAL '1 hour') RETURNING Token""",
            (digest,),
        )
        assert cursor.fetchone().Token == digest
    _reject(db_connection, 'UPDATE Customers SET auth_version = 0 WHERE CustomerID = 1')
    _reject(
        db_connection,
        """INSERT INTO PasswordResetTokens (CustomerID, Token, ExpiryDate)
                             VALUES (1, 'plain-secret-token', CURRENT_TIMESTAMP + INTERVAL '1 hour')""",
    )


def test_casefold_email_uniqueness_keeps_integrityerror_sqlstate(db_connection):
    _reject(
        db_connection,
        "SELECT sp_AddCustomer('Duplicate', 'CUSTOMER@example.test', 'test-hash', NULL, NULL)",
        code='23505',
    )
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT sp_AddCustomer('Normalized', '  NEW@example.test  ', 'test-hash', '', NULL)")
        uid = cursor.fetchone()[0]
        cursor.execute('SELECT Email, PhoneNumber FROM Customers WHERE CustomerID = %s', (uid,))
        row = cursor.fetchone()
        assert row.Email == 'new@example.test'
        assert row.PhoneNumber is None
        cursor.execute(
            "INSERT INTO NewsletterSubscribers (Email) VALUES ('SUBSCRIBER@example.test') ON CONFLICT DO NOTHING"
        )
        assert cursor.rowcount == 0
    _reject(db_connection, "INSERT INTO NewsletterSubscribers (Email) VALUES ('SUBSCRIBER@example.test')", code='23505')


def test_all_legacy_main_functions_are_callable_with_preserved_return_shapes(db_connection):
    checks = [
        (
            'SELECT * FROM sp_GetCustomerOrders(1)',
            ['orderid', 'orderdate', 'totalamount', 'status', 'paymentmethod', 'shippingaddress', 'totalitems'],
        ),
        (
            'SELECT * FROM sp_GetOrderDetails_Main(1)',
            [
                'orderid',
                'orderdate',
                'totalamount',
                'status',
                'paymentmethod',
                'shippingaddress',
                'customerid',
                'customername',
                'customeremail',
                'customerphone',
            ],
        ),
        (
            'SELECT * FROM sp_GetOrderDetails_Items(1)',
            ['orderdetailid', 'productid', 'productname', 'colorname', 'sizename', 'quantity', 'price', 'subtotal'],
        ),
        (
            'SELECT * FROM sp_SearchProducts(NULL, NULL, NULL, NULL, NULL, NULL, FALSE)',
            [
                'productid',
                'productname',
                'description',
                'price',
                'originalprice',
                'categoryid',
                'categoryname',
                'imageurl',
            ],
        ),
        (
            "SELECT * FROM sp_GetRevenueByDateRange_Daily('2026-04-01', '2026-04-30')",
            ['orderdate', 'ordercount', 'dailyrevenue'],
        ),
        (
            "SELECT * FROM sp_GetRevenueByDateRange_Category('2026-04-01', '2026-04-30')",
            ['categoryid', 'categoryname', 'categoryrevenue', 'totalquantitysold'],
        ),
    ]
    with db_connection.cursor() as cursor:
        for query, expected in checks:
            cursor.execute(query)
            assert [field[0] for field in cursor.description] == expected
            assert cursor.fetchall()
        cursor.execute("SELECT sp_AddProduct('Function Test Product', 'Synthetic', 123.45, 150, 1)")
        product_id = cursor.fetchone()[0]
        cursor.execute('SELECT sp_AddProductVariant(%s, 1, 1, 5)', (product_id,))
        variant_id = cursor.fetchone()[0]
        cursor.execute('SELECT sp_AddProductVariant(%s, 1, 1, 2)', (product_id,))
        assert cursor.fetchone()[0] == variant_id
        cursor.execute('SELECT Quantity FROM ProductVariants WHERE VariantID = %s', (variant_id,))
        assert cursor.fetchone().Quantity == 7
        cursor.execute('SELECT sp_CreateOrder(1, %s, %s)', ('cod', 'Synthetic SQL Contract Street'))
        order_id = cursor.fetchone()[0]
        cursor.execute('SELECT sp_AddOrderDetail(%s, %s, 1)', (order_id, variant_id))
        assert cursor.fetchone()[0] == 0
        cursor.execute('SELECT sp_UpdateOrderStatus(%s, %s)', (order_id, 'Processing'))
        assert cursor.fetchone()[0] == 0


def test_search_color_size_and_stock_must_match_same_variant(db_connection):
    with db_connection.cursor() as cursor:
        cursor.execute("""INSERT INTO ProductVariants (ProductID, ColorID, SizeID, Quantity)
                          VALUES (1, 2, 2, 10), (1, 1, 2, 0)""")
        cursor.execute('SELECT ProductID FROM sp_SearchProducts(NULL, 1, NULL, NULL, 1, 2, TRUE)')
        assert cursor.fetchall() == []
        cursor.execute('SELECT ProductID FROM sp_SearchProducts(NULL, 1, NULL, NULL, 1, 2, FALSE)')
        assert [row.ProductID for row in cursor.fetchall()] == [1]
        cursor.execute('SELECT ProductID FROM sp_SearchProducts(NULL, 1, NULL, NULL, 2, 1, FALSE)')
        assert cursor.fetchall() == []
        cursor.execute('SELECT ProductID FROM sp_SearchProducts(NULL, 1, 199000, 199000, 1, 1, TRUE)')
        assert [row.ProductID for row in cursor.fetchall()] == [1]


@pytest.mark.parametrize('reference', ['participant', 'creator', 'reaction', 'pin'])
def test_customer_delete_preserves_every_customer_side_chat_reference(db_connection, reference):
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT sp_AddCustomer('Retained History', %s, 'test-hash', NULL, NULL)", (f'{reference}@example.test',)
        )
        uid = cursor.fetchone()[0]
        if reference == 'participant':
            cursor.execute('INSERT INTO Participants (conversation_id, user_id) VALUES (1, %s)', (uid,))
        elif reference == 'creator':
            cursor.execute("INSERT INTO Conversations (type, created_by) VALUES ('group', %s)", (uid,))
        elif reference == 'reaction':
            cursor.execute("INSERT INTO Reactions (message_id, user_id, emoji) VALUES (1, %s, '👍')", (uid,))
        else:
            cursor.execute(
                'INSERT INTO PinnedMessages (conversation_id, message_id, pinned_by) VALUES (1, 1, %s)', (uid,)
            )
    _reject(db_connection, 'DELETE FROM Customers WHERE CustomerID = %s', (uid,), code='23503')
    with db_connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM Customers WHERE CustomerID = %s', (uid,))
        assert cursor.fetchone()[0] == 1


def test_chat_uniqueness_and_private_attachment_storage_contract(db_connection):
    _reject(db_connection, 'INSERT INTO Participants (conversation_id, user_id) VALUES (1, 1)', code='23505')
    with db_connection.cursor() as cursor:
        cursor.execute("INSERT INTO Reactions (message_id, user_id, emoji) VALUES (1, 1, '👍') ON CONFLICT DO NOTHING")
        cursor.execute("INSERT INTO Reactions (message_id, user_id, emoji) VALUES (1, 1, '👍') ON CONFLICT DO NOTHING")
        assert cursor.rowcount == 0
        cursor.execute('INSERT INTO PinnedMessages (conversation_id, message_id, pinned_by) VALUES (1, 1, 1)')
        cursor.execute("""INSERT INTO Attachments (message_id, file_url, file_name, file_type, file_size, storage_name)
                          VALUES (1, '/chat/attachment/1', 'synthetic.txt', 'file', 12,
                                  'synthetic_generated_name.txt') RETURNING storage_name""")
        assert cursor.fetchone().storage_name == 'synthetic_generated_name.txt'
        cursor.execute('SELECT * FROM vw_ConversationSummary WHERE conversation_id = 1')
        summary = cursor.fetchone()
        assert summary.member_count == 2
        assert summary.message_count == 2
        assert summary.last_message == 'Synthetic support answer'
    _reject(
        db_connection,
        'INSERT INTO PinnedMessages (conversation_id, message_id, pinned_by) VALUES (1, 1, 1)',
        code='23505',
    )
