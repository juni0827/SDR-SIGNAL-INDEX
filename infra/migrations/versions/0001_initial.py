"""Initial provenance-first Signal Index schema.

Revision ID: 0001
Revises:
"""

from alembic import op

from signal_index import models  # noqa: F401
from signal_index.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    Base.metadata.create_all(bind=bind)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcript_fts ON transcripts "
        "USING gin (to_tsvector('simple', coalesce(normalized_text, '')))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entity_trgm ON extracted_entities "
        "USING gin (normalized_value gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embedding_hnsw ON embeddings "
        "USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
