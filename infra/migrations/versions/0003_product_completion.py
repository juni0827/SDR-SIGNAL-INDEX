"""Persist graph layouts, secure credentials, and binary inbox metadata.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inbox_items ADD COLUMN IF NOT EXISTS original_filename TEXT")
    op.execute("ALTER TABLE inbox_items ADD COLUMN IF NOT EXISTS mime_type VARCHAR(120)")
    op.execute("ALTER TABLE inbox_items ADD COLUMN IF NOT EXISTS sha256 VARCHAR(64)")
    op.execute("ALTER TABLE inbox_items ADD COLUMN IF NOT EXISTS size_bytes INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_inbox_items_sha256 ON inbox_items (sha256)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_layouts (
            id VARCHAR(36) PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE,
            name VARCHAR(200) NOT NULL,
            owner_id VARCHAR(36) NOT NULL REFERENCES users(id),
            query_json JSON NOT NULL DEFAULT '{}',
            positions JSON NOT NULL DEFAULT '{}',
            viewport JSON NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_graph_layouts_name ON graph_layouts (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_graph_layouts_owner_id ON graph_layouts (owner_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS secret_records (
            id VARCHAR(36) PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE,
            key VARCHAR(160) NOT NULL UNIQUE,
            encrypted_value TEXT NOT NULL,
            key_version INTEGER NOT NULL DEFAULT 1,
            actor_id VARCHAR(36) NOT NULL REFERENCES users(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_secret_records_key ON secret_records (key)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id VARCHAR(36) PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id),
            credential_id TEXT NOT NULL UNIQUE,
            public_key TEXT NOT NULL,
            sign_count INTEGER NOT NULL DEFAULT 0,
            transports JSON NOT NULL DEFAULT '[]',
            name VARCHAR(200) NOT NULL DEFAULT 'Passkey',
            last_used_at TIMESTAMP WITH TIME ZONE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_webauthn_credentials_user_id "
        "ON webauthn_credentials (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webauthn_credentials")
    op.execute("DROP TABLE IF EXISTS secret_records")
    op.execute("DROP TABLE IF EXISTS graph_layouts")
    op.execute("DROP INDEX IF EXISTS ix_inbox_items_sha256")
    op.execute("ALTER TABLE inbox_items DROP COLUMN IF EXISTS size_bytes")
    op.execute("ALTER TABLE inbox_items DROP COLUMN IF EXISTS sha256")
    op.execute("ALTER TABLE inbox_items DROP COLUMN IF EXISTS mime_type")
    op.execute("ALTER TABLE inbox_items DROP COLUMN IF EXISTS original_filename")
