import argparse
import getpass
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User, Role, UserRole

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    parser.add_argument('--email')
    args = parser.parse_args()
    password = getpass.getpass('Contraseña del administrador: ')
    if len(password) < 12:
        raise SystemExit('La contraseña debe tener al menos 12 caracteres')
    db = SessionLocal()
    try:
        username = args.username.strip().lower()
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit('El usuario ya existe')
        role = db.scalar(select(Role).where(Role.code == 'ADMIN'))
        if role is None:
            raise SystemExit('Ejecute primero el seed de permisos')
        user = User(username=username, email=args.email, password_hash=hash_password(password))
        user.roles.append(role)
        db.add(user)
        db.commit()
        print(f'Administrador creado: {username}')
    finally:
        db.close()

if __name__ == '__main__':
    main()
