from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import Permission, Role, RolePermission

PERMISSIONS = [
    'gestion.settings.read', 'gestion.settings.manage', 'gestion.mayor.read', 'gestion.mayor.manage',
    'gestion.institutional.read', 'gestion.institutional.manage', 'gestion.gaceta.read', 'gestion.gaceta.manage',
    'gestion.gaceta.publish', 'gestion.media.read', 'gestion.media.upload', 'gestion.media.manage',
    'gestion.users.read', 'gestion.users.manage', 'gestion.roles.read', 'gestion.roles.manage', 'gestion.roles.assign',
]
EDITOR = {'gestion.settings.read', 'gestion.mayor.read', 'gestion.institutional.read', 'gestion.gaceta.read', 'gestion.gaceta.manage', 'gestion.gaceta.publish', 'gestion.media.read', 'gestion.media.upload'}

def main() -> None:
    db = SessionLocal()
    try:
        permissions = {}
        for code in PERMISSIONS:
            item = db.scalar(select(Permission).where(Permission.code == code))
            if item is None:
                item = Permission(code=code, description=code)
                db.add(item)
            permissions[code] = item
        db.flush()
        for code, name in [('ADMIN', 'Administrador'), ('EDITOR', 'Editor')]:
            role = db.scalar(select(Role).where(Role.code == code))
            if role is None:
                role = Role(code=code, name=name, description=f'Rol {name}')
                db.add(role)
            role.permissions = list(permissions.values()) if code == 'ADMIN' else [permissions[p] for p in EDITOR]
        db.commit()
        print('Permisos y roles iniciales creados/actualizados.')
    finally:
        db.close()

if __name__ == '__main__':
    main()
