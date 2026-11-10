# Despliegue — Backend Sipe Sipe Gestión

Repositorio de despliegue del backend FastAPI de **Sipe Sipe Gestión** (Gobierno Autónomo Municipal de Sipe Sipe).

Contiene únicamente lo necesario para ejecutar el backend en el servidor Debian con Docker Compose:

- API FastAPI (`backend/app/`).
- Migraciones Alembic (`backend/alembic/`, `backend/alembic.ini`).
- Dependencias fijadas (`backend/requirements.txt`).
- `Dockerfile` y `docker-compose.yml` de producción.
- Scripts operativos de inicialización (`backend/app/scripts/`).

**No** incluye el panel Flutter, pruebas automatizadas ni documentación interna de auditoría: este repositorio es sólo el backend.

---

## Arquitectura de publicación

```
Internet
   ↓
Cloudflare
   ↓
api.sipesipe.gob.bo
   ↓
Cloudflare Tunnel   (cloudflared corre en el servidor Debian)
   ↓
127.0.0.1:8001
   ↓
FastAPI Sipe Sipe Gestión
   ↓
PostgreSQL  gestion_sipe   (red interna de Docker, nunca expuesta)
   ↓
volumen Docker  gestion_storage  (PDFs e imágenes)
```

No hay nginx público: **la publicación la hace Cloudflare Tunnel**. El
contenedor del backend escucha sólo en `127.0.0.1:8001` dentro del host.

---

## 1. Requisitos del servidor

- Debian o Ubuntu.
- Git.
- Docker Engine.
- Plugin Docker Compose (v2): `docker compose version`.
- Acceso a Internet para descargar `postgres:16-alpine` y `python:3.12-slim`.
- `cloudflared` se instalará posteriormente, cuando se tenga control DNS de
  `sipesipe.gob.bo`.

Comprobación inicial:

```bash
docker --version
docker compose version
```

---

## 2. Primer despliegue

```bash
# 1. Clonar este repositorio
git clone https://github.com/AndyGuzmanEscalera/sipe-sipe-gestion-deploy.git
cd sipe-sipe-gestion-deploy

# 2. Crear la configuración local
cp .env.example .env
nano .env
```

### 2.1 Generar el secreto JWT

El secreto se genera **directamente en el servidor** y nunca se versiona:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copiar el resultado en `JWT_ACCESS_SECRET` dentro de `.env`.

### 2.2 Generar la contraseña de PostgreSQL

Debe ser una contraseña fuerte e independiente del secreto JWT:

```bash
openssl rand -base64 24
```

Copiar el resultado en `POSTGRES_PASSWORD` dentro de `.env`.

### 2.3 Revisar las variables obligatorias

| Variable | Valor en `.env` |
|---|---|
| `POSTGRES_PASSWORD` | generada en el servidor |
| `JWT_ACCESS_SECRET` | `secrets.token_urlsafe(48)` |
| `PUBLIC_BASE_URL` | `https://api.sipesipe.gob.bo` |
| `APP_ENV` | `production` |
| `COOKIE_SECURE` | `true` |
| `CORS_ALLOW_ORIGINS` | `https://sipesipe-gestion.pages.dev,https://gestion.sipesipe.gob.bo` |

`CORS_ALLOW_ORIGINS` es una **lista separada por comas** (así la parsea
`backend/app/core/config.py`). Durante la transición se permiten ambos
orígenes; cuando el panel esté en el dominio definitivo se puede retirar
`https://sipesipe-gestion.pages.dev`.

El backend **se niega a arrancar** en `production` si `PUBLIC_BASE_URL` está
vacía, usa `localhost`/`127.0.0.1` o no es `https://`, o si `COOKIE_SECURE` no
es `true`. Es intencional: evita publicar URLs de media que apunten a la
máquina local.

### 2.4 Levantar el servicio

```bash
# Validar la configuración interpolada
docker compose config

# Construir y levantar en segundo plano
docker compose up -d --build

# Ver contenedores y healthchecks
docker compose ps

# Aplicar migraciones (base gestion_sipe)
docker compose exec backend alembic upgrade head

# Crear permisos y roles iniciales (ADMIN, EDITOR)
docker compose exec backend python -m app.scripts.seed

# Crear el primer administrador (pide la contraseña de forma interactiva)
docker compose exec backend python -m app.scripts.create_admin --username admin --email admin@gamsipesipe.gob.bo
```

### 2.5 Probar el servicio

Las rutas reales de salud del proyecto son `/health` y `/health/database`:

```bash
curl http://127.0.0.1:8001/health
# {"status":"ok","service":"sipe-sipe-gestion-api"}

curl http://127.0.0.1:8001/health/database
# {"status":"ok","database":"connected"}
```

Ambos contenedores exponen `healthcheck`: `docker compose ps` debe mostrar
`healthy` en el servicio de base de datos y en el del backend.

Documentación interactiva de la API: `http://127.0.0.1:8001/docs`.

---

## 3. Publicación mediante Cloudflare Tunnel

```
api.sipesipe.gob.bo
    ↓
Cloudflare Tunnel
    ↓
http://127.0.0.1:8001
```

Puntos importantes:

- **No abrir el puerto 8001 en el router.** El backend queda ligado a
  `127.0.0.1` y sólo es alcanzable desde el propio servidor.
- **No exponer PostgreSQL.** El puerto 5433 también está ligado a `127.0.0.1`
  y nunca debe publicarse. Dentro de la red de Docker el backend usa el
  nombre del servicio `postgres`.
- **`cloudflared` correrá en el servidor Debian**, no como contenedor de este
  compose.
- El hostname final será **`api.sipesipe.gob.bo`**.
- `PUBLIC_BASE_URL` debe ser **`https://api.sipesipe.gob.bo`**: es la base de
  las URLs de media que devuelve la API y que consume el sitio público.

La configuración real del túnel (credencial de Cloudflare, `config.yml`,
servicio systemd) se realizará después de tener control DNS de
`sipesipe.gob.bo`. No forma parte de este repositorio.

---

## 4. Variables de entorno

Todas las variables están documentadas en `.env.example`. Resumen:

| Variable | Obligatoria | Descripción |
|---|---|---|
| `APP_ENV` | sí | `production` |
| `APP_NAME` | no | Nombre de la aplicación |
| `APP_VERSION` | no | Versión reportada por la API |
| `POSTGRES_DB` | sí | `gestion_sipe` |
| `POSTGRES_USER` | sí | `sipe_app` |
| `POSTGRES_PASSWORD` | sí | generada en el servidor |
| `POSTGRES_HOST` / `POSTGRES_PORT` | no | `postgres` / `5432` (red de Docker) |
| `BACKEND_PORT` | no | puerto local publicado (8001), destino del túnel |
| `GESTION_POSTGRES_PORT` | no | puerto local de PostgreSQL (5433), loopback |
| `GESTION_DB_CONTAINER` / `GESTION_BACKEND_CONTAINER` | no | nombres de contenedor |
| `JWT_ACCESS_SECRET` | sí | `secrets.token_urlsafe(48)`, mínimo 32 caracteres |
| `JWT_ISSUER` / `JWT_AUDIENCE` | no | claims del token |
| `ACCESS_TOKEN_TTL_MINUTES` | no | `15` |
| `REFRESH_TOKEN_TTL_DAYS` | no | `7` |
| `COOKIE_NAME` | no | `gestion_refresh_token` |
| `COOKIE_PATH` | no | `/api/admin/auth` |
| `COOKIE_SECURE` | sí en producción | `true` |
| `COOKIE_SAMESITE` | no | `lax` |
| `CORS_ALLOW_ORIGINS` | sí | lista separada por comas |
| `CORS_ALLOW_CREDENTIALS` | no | `true` |
| `STORAGE_ROOT` | no | `/app/storage` dentro del contenedor |
| `MAX_PDF_SIZE_MB` | no | `25` |
| `MAX_IMAGE_SIZE_MB` | no | `8` |
| `PUBLIC_BASE_URL` | sí | `https://api.sipesipe.gob.bo` |

`DATABASE_URL` **no** se define en `.env`: `docker-compose.yml` la compone con
`POSTGRES_*` para que apunte al servicio `postgres` de la red interna.

---

## 5. Persistencia

| Volumen Docker | Contenido | Ruta real en el host |
|---|---|---|
| `gestion_postgres_data` | Base de datos `gestion_sipe` | `/var/lib/docker/volumes/sipe-sipe-gestion-deploy_gestion_postgres_data/_data` |
| `gestion_storage` | PDFs e imágenes subidos | `/var/lib/docker/volumes/sipe-sipe-gestion-deploy_gestion_storage/_data` |

Dentro del contenedor `backend`, los archivos viven en `STORAGE_ROOT=/app/storage`.

Para localizar los volúmenes sin asumir rutas:

```bash
docker volume ls
docker volume inspect sipe-sipe-gestion-deploy_gestion_storage
docker volume inspect sipe-sipe-gestion-deploy_gestion_storage --format '{{ .Mountpoint }}'
docker volume inspect sipe-sipe-gestion-deploy_gestion_postgres_data --format '{{ .Mountpoint }}'
```

**Importante:** `docker compose down` **no** borra los volúmenes. Sólo
`docker compose down -v` o `docker volume rm` los eliminan.

Nunca se borra físicamente un archivo subido: la baja es lógica
(`media.is_active = false`, `deleted_at`). Al reemplazar un PDF o una foto, el
archivo anterior se marca `superseded_at` y se conserva en disco para
auditoría.

---

## 6. Respaldo

Un respaldo completo de Sipe Sipe Gestión requiere **dos** cosas:

1. La base de datos PostgreSQL `gestion_sipe`.
2. El volumen `gestion_storage` con PDFs e imágenes.

PostgreSQL no contiene el binario de los archivos: respaldar sólo la base
deja el sistema inconsistente.

### 6.1 PostgreSQL

```bash
mkdir -p /var/backups/sipe-sipe-gestion

docker compose exec -T postgres pg_dump -U sipe_app gestion_sipe \
  > /var/backups/sipe-sipe-gestion/backup_gestion_$(date +%Y%m%d_%H%M).sql
```

Si `POSTGRES_USER` o `POSTGRES_DB` se cambiaran en `.env`, usar esos valores.

### 6.2 Volumen de archivos

```bash
docker volume ls | grep gestion_storage

VOL=$(docker volume inspect sipe-sipe-gestion-deploy_gestion_storage --format '{{ .Mountpoint }}')
tar -C "$VOL" -czf /var/backups/sipe-sipe-gestion/backup_storage_$(date +%Y%m%d_%H%M).tar.gz .
```

Alternativa sin depender de la ruta del host:

```bash
docker run --rm \
  -v sipe-sipe-gestion-deploy_gestion_storage:/data:ro \
  -v /var/backups/sipe-sipe-gestion:/backup \
  alpine tar -C /data -czf /backup/backup_storage_$(date +%Y%m%d_%H%M).tar.gz .
```

### 6.3 Restauración

```bash
# Base de datos
docker compose exec -T postgres psql -U sipe_app gestion_sipe < backup_gestion_AAAAMMDD.sql

# Volumen de archivos
docker run --rm \
  -v sipe-sipe-gestion-deploy_gestion_storage:/data \
  -v /var/backups/sipe-sipe-gestion:/backup:ro \
  alpine sh -c "tar -C /data -xzf /backup/backup_storage_AAAAMMDD.tar.gz"
```

Conviene automatizarlo con `cron` y verificar periódicamente que un respaldo
restaura correctamente.

---

## 7. Actualizaciones futuras

```bash
cd sipe-sipe-gestion-deploy

git pull
docker compose build backend
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose ps
curl http://127.0.0.1:8001/health
```

El seed y la creación de administrador **no** se reejecutan en cada
actualización: son idempotentes, pero no son necesarios.

**Nunca usar `docker compose down -v` en producción** salvo autorización
explícita: `-v` elimina los volúmenes `gestion_postgres_data` y
`gestion_storage` y con ellos la base y todos los archivos subidos.

Para una actualización sin downtime se recomienda `docker compose build backend`
y `docker compose up -d` (recrea sólo el contenedor del backend; PostgreSQL y
el volumen no se tocan).

---

## 8. Rollback básico

```bash
cd sipe-sipe-gestion-deploy

# 1. Volver a la versión anterior del código
git log --oneline -5
git checkout <commit-anterior>

# 2. Reconstruir y reiniciar
docker compose build backend
docker compose up -d
docker compose ps
```

Si la actualización incluía migraciones, el rollback de esquema es manual:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic history
```

Las migraciones de este proyecto son `gestion_0001` (esquema inicial) y
`gestion_0002` (columnas de ciclo de vida de `media`, sólo aditiva). Ambas son
reversibles con `alembic downgrade -1`.

Para retroceder más de una versión, restaurar el respaldo de la base y el del
volumen de archivos.

---

## 9. Operación diaria

```bash
docker compose ps                       # estado y healthchecks
docker compose logs -f backend          # log en vivo
docker compose logs --tail=100 postgres # log de base de datos
docker compose restart backend          # reiniciar sólo la API
docker compose exec backend alembic current
docker compose exec backend python -m app.scripts.create_admin --username nuevo --email nuevo@gamsipesipe.gob.bo
```

---

## 10. Composición del repositorio

```
.
├── .env.example          Plantilla de configuración (sin secretos)
├── .gitattributes
├── .gitignore
├── README.md
├── docker-compose.yml    postgres (gestion_sipe) + backend
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       ├── 0001_initial.py
    │       └── 0002_media_lifecycle.py
    └── app/
        ├── __init__.py
        ├── auth.py           Sesiones, JWT y RBAC
        ├── main.py           Rutas de la API
        ├── models.py         Modelos SQLAlchemy
        ├── common/schemas.py Esquemas compartidos
        ├── core/             Configuración, BD, seguridad, CORS, storage
        └── scripts/          seed y create_admin
```
