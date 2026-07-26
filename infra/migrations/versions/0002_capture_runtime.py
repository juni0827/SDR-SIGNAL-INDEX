"""Add capture runtime state.

Revision ID: 0002
Revises: 0001

The original 0001 migration used metadata.create_all(), so fresh databases may
already contain these columns after the model update. IF NOT EXISTS keeps this
upgrade safe for both existing and fresh installations.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE capture_jobs ADD COLUMN IF NOT EXISTS "
        "recording_id VARCHAR(36) REFERENCES recordings(id)"
    )
    op.execute(
        "ALTER TABLE capture_jobs ADD COLUMN IF NOT EXISTS "
        "next_run_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE capture_jobs ADD COLUMN IF NOT EXISTS "
        "last_started_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE capture_jobs ADD COLUMN IF NOT EXISTS "
        "last_finished_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE capture_jobs ADD COLUMN IF NOT EXISTS "
        "last_error TEXT"
    )
    op.execute(
        "ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS "
        "job_type VARCHAR(40) NOT NULL DEFAULT 'INITIAL'"
    )
    op.execute(
        "ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS "
        "parameters JSON NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_capture_jobs_recording_id "
        "ON capture_jobs (recording_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_capture_jobs_next_run_at "
        "ON capture_jobs (next_run_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_provenance_source_record_hash "
        "ON provenance (source_id, record_type, raw_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_capture_jobs_next_run_at")
    op.execute("DROP INDEX IF EXISTS ix_capture_jobs_recording_id")
    op.execute("DROP INDEX IF EXISTS uq_provenance_source_record_hash")
    op.execute("ALTER TABLE capture_jobs DROP COLUMN IF EXISTS last_finished_at")
    op.execute("ALTER TABLE capture_jobs DROP COLUMN IF EXISTS last_error")
    op.execute("ALTER TABLE capture_jobs DROP COLUMN IF EXISTS last_started_at")
    op.execute("ALTER TABLE capture_jobs DROP COLUMN IF EXISTS next_run_at")
    op.execute("ALTER TABLE capture_jobs DROP COLUMN IF EXISTS recording_id")
    op.execute("ALTER TABLE processing_jobs DROP COLUMN IF EXISTS parameters")
    op.execute("ALTER TABLE processing_jobs DROP COLUMN IF EXISTS job_type")
