"""Add media lifecycle columns (superseded_at, deleted_at) and active index."""
from alembic import op

revision = "gestion_0002"
down_revision = "gestion_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE media ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE media ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_media_active ON media (kind, is_active)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_media_active")
    op.execute("ALTER TABLE media DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE media DROP COLUMN IF EXISTS superseded_at")
