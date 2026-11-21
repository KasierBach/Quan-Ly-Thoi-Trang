-- Phase 5 OAuth: additive schema only. Do not apply to a live database.
-- Deploy application None-password guards before allowing OAuth-only accounts.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

-- NULL means password authentication is unavailable; never store a dummy password.
ALTER TABLE Customers ALTER COLUMN Password DROP NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email_lower ON Customers (lower(Email));

CREATE TABLE IF NOT EXISTS OAuthIdentities (
    identity_id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES Customers(CustomerID) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL CHECK (provider IN ('google', 'github')),
    issuer VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL CHECK (length(subject) > 0),
    email VARCHAR(254) NOT NULL,
    email_verified BOOLEAN NOT NULL CHECK (email_verified IS TRUE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, issuer, subject),
    UNIQUE (customer_id, provider),
    CHECK ((provider = 'google' AND issuer = 'https://accounts.google.com')
        OR (provider = 'github' AND issuer = 'https://github.com'))
);

-- One-use authorization/reauthentication ledger works across workers/restarts.
-- Hashes only identify state/session binding. Temporary auth_data contains PKCE
-- verifier and callback/nonce, never an access/refresh token or client secret.
CREATE TABLE IF NOT EXISTS OAuthStates (
    state_digest CHAR(64) PRIMARY KEY CHECK (state_digest ~ '^[0-9a-f]{64}$'),
    binding_digest CHAR(64) NOT NULL CHECK (binding_digest ~ '^[0-9a-f]{64}$'),
    purpose VARCHAR(20) NOT NULL CHECK (purpose IN ('authorization', 'reauth')),
    auth_data JSONB NOT NULL CHECK (jsonb_typeof(auth_data) = 'object'),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expiry ON OAuthStates (expires_at);
COMMIT;
