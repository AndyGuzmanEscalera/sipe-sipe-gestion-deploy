"""initial gestion schema"""
from alembic import op

revision = "gestion_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("""
    CREATE TABLE users (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(), username VARCHAR(80) NOT NULL UNIQUE,
      email VARCHAR(255) UNIQUE, password_hash TEXT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
      last_login_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE roles (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), code VARCHAR(100) NOT NULL UNIQUE, name VARCHAR(150) NOT NULL, description TEXT, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE permissions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), code VARCHAR(150) NOT NULL UNIQUE, description TEXT NOT NULL);
    CREATE TABLE user_roles (user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE, PRIMARY KEY(user_id, role_id));
    CREATE TABLE role_permissions (role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE, permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE, PRIMARY KEY(role_id, permission_id));
    CREATE TABLE auth_sessions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, refresh_token_hash VARCHAR(64) NOT NULL UNIQUE, expires_at TIMESTAMPTZ NOT NULL, last_used_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE site_settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL DEFAULT '', updated_by_user_id UUID REFERENCES users(id), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE institutional_content (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), mission TEXT NOT NULL DEFAULT '', vision TEXT NOT NULL DEFAULT '', updated_by_user_id UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE institutional_values (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), value VARCHAR(500) NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE media (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), original_filename VARCHAR(255) NOT NULL, mime_type VARCHAR(120) NOT NULL, size_bytes BIGINT NOT NULL, sha256 VARCHAR(64) NOT NULL, storage_path TEXT NOT NULL UNIQUE, kind VARCHAR(30) NOT NULL, uploaded_by_user_id UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), is_active BOOLEAN NOT NULL DEFAULT TRUE);
    CREATE TABLE mayors (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(200) NOT NULL DEFAULT '', title VARCHAR(200) NOT NULL DEFAULT '', welcome_title VARCHAR(300) NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '', photo_media_id UUID REFERENCES media(id), photo_note TEXT NOT NULL DEFAULT '', is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE gaceta_categories (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(150) NOT NULL UNIQUE, description TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE gaceta_documents (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), category_id UUID NOT NULL REFERENCES gaceta_categories(id), number VARCHAR(100) NOT NULL, title VARCHAR(500) NOT NULL, description TEXT, published_at DATE NOT NULL, pdf_media_id UUID NOT NULL REFERENCES media(id), is_published BOOLEAN NOT NULL DEFAULT FALSE, created_by_user_id UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ);
    CREATE UNIQUE INDEX uq_gaceta_number_active ON gaceta_documents(number) WHERE deleted_at IS NULL;
    CREATE INDEX ix_gaceta_published ON gaceta_documents(is_published, published_at DESC) WHERE deleted_at IS NULL;
    CREATE INDEX ix_media_kind ON media(kind, is_active);
    """)


def downgrade() -> None:
    for name in ["gaceta_documents", "gaceta_categories", "mayors", "media", "institutional_values", "institutional_content", "site_settings", "auth_sessions", "role_permissions", "user_roles", "permissions", "roles", "users"]:
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
