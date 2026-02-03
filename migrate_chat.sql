-- Add theme_color and default_emoji to Conversations table
ALTER TABLE Conversations ADD COLUMN IF NOT EXISTS theme_color VARCHAR(50);
ALTER TABLE Conversations ADD COLUMN IF NOT EXISTS default_emoji VARCHAR(50);

-- Ensure nickname and is_muted exist in Participants (they do, but just in case of different environments)
ALTER TABLE Participants ADD COLUMN IF NOT EXISTS nickname VARCHAR(100);
ALTER TABLE Participants ADD COLUMN IF NOT EXISTS is_muted BOOLEAN DEFAULT FALSE;
