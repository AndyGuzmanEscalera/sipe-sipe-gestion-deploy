"""Add authorities table for municipal cabinet."""
from alembic import op

revision = "gestion_0003"
down_revision = "gestion_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE authorities (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      name VARCHAR(200) NOT NULL DEFAULT '',
      professional_title VARCHAR(200) NOT NULL DEFAULT '',
      position VARCHAR(200) NOT NULL DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      photo_media_id UUID REFERENCES media(id),
      display_order INTEGER NOT NULL DEFAULT 0,
      is_active BOOLEAN NOT NULL DEFAULT TRUE,
      is_published BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_authorities_public ON authorities (is_active, is_published, display_order);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS authorities CASCADE")
