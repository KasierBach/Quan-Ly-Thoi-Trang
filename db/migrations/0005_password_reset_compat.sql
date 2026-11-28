-- Retire plaintext legacy reset credentials while keeping reset history.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('thua2_main_bootstrap'));

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'passwordresettokens'::regclass AND attname = 'token' AND atttypid = 'uuid'::regtype
    ) THEN
        ALTER TABLE PasswordResetTokens
            ALTER COLUMN Token DROP DEFAULT,
            ALTER COLUMN Token TYPE VARCHAR(100) USING Token::text;
    END IF;
END;
$$;

UPDATE PasswordResetTokens
SET Token = encode(sha256(convert_to('retired-reset-token:' || Token::text, 'UTF8')), 'hex'),
    IsUsed = TRUE
WHERE Token::text !~ '^[0-9a-f]{64}$';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'passwordresettokens'::regclass AND conname = 'passwordresettokens_sha256'
    ) THEN
        ALTER TABLE PasswordResetTokens
            ADD CONSTRAINT passwordresettokens_sha256 CHECK (Token::text ~ '^[0-9a-f]{64}$') NOT VALID;
    END IF;
END;
$$;
ALTER TABLE PasswordResetTokens VALIDATE CONSTRAINT passwordresettokens_sha256;
COMMIT;
