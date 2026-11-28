BEGIN;
SET LOCAL search_path = public, pg_catalog;

CREATE TABLE IF NOT EXISTS ContactReplyDeliveries (
    delivery_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id INTEGER NOT NULL REFERENCES ContactMessages(MessageID) ON DELETE CASCADE,
    reply_digest VARCHAR(64) NOT NULL,
    delivery_status VARCHAR(10) NOT NULL DEFAULT 'Sending' CHECK (delivery_status IN ('Sending', 'Sent', 'Failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    UNIQUE (contact_id, reply_digest),
    CHECK ((delivery_status = 'Sending') = (finished_at IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_contact_deliveries_latest
    ON ContactReplyDeliveries (contact_id, started_at DESC, delivery_id DESC);

COMMIT;
