from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import re
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.auth import auth_response, create_access_token, ensure_permission, get_current_user, login_user, refresh_user, revoke_from_request, user_response, require_permission, set_refresh_cookie, clear_refresh_cookie
from app.core.config import get_settings
from app.core.cors import configure_cors
from app.core.database import get_db
from app.core.error_middleware import SafeErrorMiddleware
from app.core.security import clear_refresh_cookie, set_refresh_cookie
from app.core.storage import get_storage_service
from app.models import GacetaCategory, GacetaDocument, InstitutionalContent, InstitutionalValue, Mayor, Media, Permission, Role, SiteSetting, User
from app.common.schemas import PaginatedResponse, paginate

settings = get_settings()
app = FastAPI(title='Sipe Sipe Gestión API', version=settings.app_version)
app.add_middleware(SafeErrorMiddleware)
configure_cors(app, settings)

class LoginRequest(BaseModel):
    username: str
    password: str

class SettingValues(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = ''
    shortName: str = ''
    motto: str = ''
    locationLine: str = ''
    email: str = ''
    supportEmail: str = ''
    phone: str = ''
    address: str = ''
    hours: str = ''
    copyright: str = ''
    edition: str = ''
    facebook: str = ''
    instagram: str = ''
    youtube: str = ''

class MayorPayload(BaseModel):
    name: str = Field(max_length=200)
    title: str = Field(max_length=200)
    welcome_title: str = Field(default='', max_length=300)
    message: str = ''
    photo_note: str = ''

class InstitutionalPayload(BaseModel):
    mission: str = ''
    vision: str = ''

class ValuePayload(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    sort_order: int = 0
    is_active: bool = True

class CategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True

class UserPayload(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=12)
    is_active: bool = True
    role_ids: list[uuid.UUID] = []

class RolePayload(BaseModel):
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    is_active: bool = True
    permission_ids: list[uuid.UUID] = []

def setting_response(db: Session) -> dict:
    values = {row.key: row.value for row in db.scalars(select(SiteSetting)).all()}
    return values

def media_url(media_id: uuid.UUID | None) -> str | None:
    return f'{settings.public_base_url}/api/public/media/{media_id}' if media_id else None

def media_response(row: Media | None) -> dict | None:
    if row is None:
        return None
    return {'id': str(row.id), 'original_filename': row.original_filename, 'mime_type': row.mime_type, 'size_bytes': row.size_bytes, 'sha256': row.sha256, 'kind': row.kind, 'url': media_url(row.id)}

def media_admin_response(row: Media) -> dict:
    return {
        'id': str(row.id),
        'original_filename': row.original_filename,
        'mime_type': row.mime_type,
        'size_bytes': row.size_bytes,
        'sha256': row.sha256,
        'kind': row.kind,
        'storage_path': row.storage_path,
        'url': media_url(row.id),
        'is_active': row.is_active,
        'superseded_at': row.superseded_at.isoformat() if row.superseded_at else None,
        'deleted_at': row.deleted_at.isoformat() if row.deleted_at else None,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    }

def supersede_media(db: Session, row: Media | None) -> None:
    """Marca un archivo como reemplazado.

    El binario NO se borra del disco: se conserva para auditoría. El archivo
    deja de servirse públicamente porque `is_active` pasa a False.
    """
    if row is None or not row.is_active:
        return
    row.is_active = False
    row.superseded_at = datetime.now(timezone.utc)

def store_upload(upload: UploadFile, kind: str, owner_id: uuid.UUID, db: Session) -> Media:
    allowed = {'pdf': {'application/pdf'}, 'image': {'image/jpeg', 'image/png', 'image/webp'}}
    mime = (upload.content_type or '').lower()
    if mime not in allowed[kind]:
        raise HTTPException(422, f'Tipo de archivo no permitido: {mime}')
    payload = upload.file.read()
    maximum = settings.max_pdf_size_bytes if kind == 'pdf' else settings.max_image_size_bytes
    if not payload or len(payload) > maximum:
        raise HTTPException(413, 'Archivo vacío o supera el tamaño máximo')
    if kind == 'pdf' and not payload.startswith(b'%PDF-'):
        raise HTTPException(422, 'El archivo no contiene una firma PDF válida')
    if kind == 'image' and not (payload.startswith(b'\xff\xd8\xff') or payload.startswith(b'\x89PNG') or payload.startswith(b'RIFF')):
        raise HTTPException(422, 'El archivo no contiene una imagen válida')
    name = Path(upload.filename or 'archivo').name
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('._')[:200] or 'archivo'
    row_id = uuid.uuid4()
    extension = Path(safe).suffix.lower() or ('.pdf' if kind == 'pdf' else '.bin')
    key = f'{"gaceta" if kind == "pdf" else "media"}/{datetime.now().year}/{row_id}/{row_id}{extension}'
    get_storage_service().put(key, payload)
    row = Media(id=row_id, original_filename=safe, mime_type=mime, size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), storage_path=key, kind=kind, uploaded_by_user_id=owner_id)
    db.add(row)
    db.flush()
    return row

@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok', 'service': settings.app_name}

@app.get('/health/database')
def health_database(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(select(func.count()).select_from(User))
    return {'status': 'ok', 'database': 'connected'}

@app.post('/api/admin/auth/login')
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user, raw = login_user(db, body.username, body.password)
    return auth_response(response, db, user, raw)

@app.post('/api/admin/auth/refresh')
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(settings.cookie_name)
    if not raw:
        raise HTTPException(401, 'Sesión inválida')
    user, new_raw = refresh_user(db, raw)
    token, expires = create_access_token(user.id)
    set_refresh_cookie(response, new_raw)
    return {'access_token': token, 'expires_in': expires}

@app.post('/api/admin/auth/logout', status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    revoke_from_request(db, request)
    clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response

@app.get('/api/admin/auth/me')
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_response(db, user)

@app.get('/api/public/site-settings')
def public_settings(db: Session = Depends(get_db)):
    return setting_response(db)

@app.get('/api/admin/site-settings')
def admin_settings(user: User = Depends(require_permission('gestion.settings.read')), db: Session = Depends(get_db)):
    return setting_response(db)

@app.put('/api/admin/site-settings')
def update_settings(body: SettingValues, user: User = Depends(require_permission('gestion.settings.manage')), db: Session = Depends(get_db)):
    for key, value in body.model_dump().items():
        row = db.get(SiteSetting, key)
        if row is None:
            db.add(SiteSetting(key=key, value=value, updated_by_user_id=user.id))
        else:
            row.value, row.updated_by_user_id = value, user.id
    db.commit()
    return setting_response(db)

def mayor_response(row: Mayor | None) -> dict | None:
    if row is None:
        return None
    return {'id': str(row.id), 'name': row.name, 'title': row.title, 'welcome_title': row.welcome_title, 'message': row.message, 'photo_note': row.photo_note, 'photo': media_response(row.photo), 'is_active': row.is_active}

@app.get('/api/public/mayor')
def public_mayor(db: Session = Depends(get_db)):
    return mayor_response(db.scalar(select(Mayor).where(Mayor.is_active.is_(True)).order_by(Mayor.updated_at.desc())))

@app.get('/api/admin/mayor')
def admin_mayor(user: User = Depends(require_permission('gestion.mayor.read')), db: Session = Depends(get_db)):
    return mayor_response(db.scalar(select(Mayor).order_by(Mayor.updated_at.desc())))

@app.post('/api/admin/mayor')
def create_mayor(name: str = Form(''), title: str = Form(''), welcome_title: str = Form(''), message: str = Form(''), photo_note: str = Form(''), photo: UploadFile | None = File(default=None), user: User = Depends(require_permission('gestion.mayor.manage')), db: Session = Depends(get_db)):
    row = Mayor(name=name, title=title, welcome_title=welcome_title, message=message, photo_note=photo_note)
    if photo:
        row.photo = store_upload(photo, 'image', user.id, db)
    db.query(Mayor).update({Mayor.is_active: False})
    db.add(row)
    db.commit()
    db.refresh(row)
    return mayor_response(row)

@app.put('/api/admin/mayor/{mayor_id}')
def update_mayor(mayor_id: uuid.UUID, name: str = Form(''), title: str = Form(''), welcome_title: str = Form(''), message: str = Form(''), photo_note: str = Form(''), photo: UploadFile | None = File(default=None), user: User = Depends(require_permission('gestion.mayor.manage')), db: Session = Depends(get_db)):
    row = db.get(Mayor, mayor_id)
    if row is None:
        raise HTTPException(404, 'Alcalde no encontrado')
    row.name, row.title, row.welcome_title, row.message, row.photo_note = name, title, welcome_title, message, photo_note
    if photo:
        previous_photo = row.photo
        row.photo = store_upload(photo, 'image', user.id, db)
        supersede_media(db, previous_photo)
    row.is_active = True
    db.query(Mayor).filter(Mayor.id != row.id).update({Mayor.is_active: False})
    db.commit()
    db.refresh(row)
    return mayor_response(row)

@app.get('/api/public/institutional')
def public_institutional(db: Session = Depends(get_db)):
    row = db.scalar(select(InstitutionalContent).order_by(InstitutionalContent.created_at))
    values = db.scalars(select(InstitutionalValue).where(InstitutionalValue.is_active.is_(True)).order_by(InstitutionalValue.sort_order, InstitutionalValue.created_at)).all()
    return {'mission': row.mission if row else '', 'vision': row.vision if row else '', 'values': [{'id': str(x.id), 'value': x.value, 'sort_order': x.sort_order} for x in values]}

@app.get('/api/admin/institutional')
def admin_institutional(user: User = Depends(require_permission('gestion.institutional.read')), db: Session = Depends(get_db)):
    return public_institutional(db)

@app.put('/api/admin/institutional')
def update_institutional(body: InstitutionalPayload, user: User = Depends(require_permission('gestion.institutional.manage')), db: Session = Depends(get_db)):
    row = db.scalar(select(InstitutionalContent).order_by(InstitutionalContent.created_at))
    if row is None:
        row = InstitutionalContent()
        db.add(row)
    row.mission, row.vision, row.updated_by_user_id = body.mission, body.vision, user.id
    db.commit()
    return public_institutional(db)

@app.get('/api/admin/institutional/values')
def list_values(user: User = Depends(require_permission('gestion.institutional.read')), db: Session = Depends(get_db)):
    rows = db.scalars(select(InstitutionalValue).order_by(InstitutionalValue.sort_order, InstitutionalValue.created_at)).all()
    return [{'id': str(x.id), 'value': x.value, 'sort_order': x.sort_order, 'is_active': x.is_active} for x in rows]

@app.post('/api/admin/institutional/values')
def create_value(body: ValuePayload, user: User = Depends(require_permission('gestion.institutional.manage')), db: Session = Depends(get_db)):
    row = InstitutionalValue(**body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {'id': str(row.id), **body.model_dump()}

@app.put('/api/admin/institutional/values/{value_id}')
def update_value(value_id: uuid.UUID, body: ValuePayload, user: User = Depends(require_permission('gestion.institutional.manage')), db: Session = Depends(get_db)):
    row = db.get(InstitutionalValue, value_id)
    if row is None: raise HTTPException(404, 'Valor no encontrado')
    for key, value in body.model_dump().items(): setattr(row, key, value)
    db.commit(); return {'id': str(row.id), **body.model_dump()}

@app.post('/api/admin/institutional/values/{value_id}/deactivate')
def deactivate_value(value_id: uuid.UUID, user: User = Depends(require_permission('gestion.institutional.manage')), db: Session = Depends(get_db)):
    row = db.get(InstitutionalValue, value_id)
    if row is None: raise HTTPException(404, 'Valor no encontrado')
    row.is_active = False; db.commit(); return {'id': str(row.id), 'is_active': False}

def category_response(row: GacetaCategory) -> dict:
    return {'id': str(row.id), 'name': row.name, 'description': row.description, 'sort_order': row.sort_order, 'is_active': row.is_active}

@app.get('/api/admin/gaceta/categories')
def categories(user: User = Depends(require_permission('gestion.gaceta.read')), db: Session = Depends(get_db)):
    return [category_response(x) for x in db.scalars(select(GacetaCategory).order_by(GacetaCategory.sort_order, GacetaCategory.name)).all()]

@app.post('/api/admin/gaceta/categories')
def create_category(body: CategoryPayload, user: User = Depends(require_permission('gestion.gaceta.manage')), db: Session = Depends(get_db)):
    row = GacetaCategory(**body.model_dump()); db.add(row)
    try: db.commit()
    except Exception as exc: db.rollback(); raise HTTPException(409, 'La categoría ya existe') from exc
    db.refresh(row); return category_response(row)

@app.put('/api/admin/gaceta/categories/{category_id}')
def update_category(category_id: uuid.UUID, body: CategoryPayload, user: User = Depends(require_permission('gestion.gaceta.manage')), db: Session = Depends(get_db)):
    row = db.get(GacetaCategory, category_id)
    if row is None: raise HTTPException(404, 'Categoría no encontrada')
    for key, value in body.model_dump().items(): setattr(row, key, value)
    db.commit(); return category_response(row)

@app.post('/api/admin/gaceta/categories/{category_id}/{action}')
def toggle_category(category_id: uuid.UUID, action: str, user: User = Depends(require_permission('gestion.gaceta.manage')), db: Session = Depends(get_db)):
    if action not in {'activate', 'deactivate'}: raise HTTPException(404, 'Acción no encontrada')
    row = db.get(GacetaCategory, category_id)
    if row is None: raise HTTPException(404, 'Categoría no encontrada')
    row.is_active = action == 'activate'; db.commit(); return category_response(row)

def document_response(row: GacetaDocument) -> dict:
    return {'id': str(row.id), 'category_id': str(row.category_id), 'category': category_response(row.category), 'number': row.number, 'title': row.title, 'description': row.description, 'published_at': row.published_at.isoformat(), 'is_published': row.is_published, 'pdf': media_response(row.pdf)}

def document_query(db: Session, public: bool = False, q: str | None = None, category_id: uuid.UUID | None = None):
    query = select(GacetaDocument).where(GacetaDocument.deleted_at.is_(None))
    if public: query = query.where(GacetaDocument.is_published.is_(True))
    if q: query = query.where((GacetaDocument.title.ilike(f'%{q}%')) | (GacetaDocument.number.ilike(f'%{q}%')))
    if category_id: query = query.where(GacetaDocument.category_id == category_id)
    return query.order_by(GacetaDocument.published_at.desc(), GacetaDocument.created_at.desc())

@app.get('/api/public/gaceta')
def public_gaceta(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), q: str | None = None, category: uuid.UUID | None = None, db: Session = Depends(get_db)):
    query = document_query(db, True, q, category)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return paginate([document_response(x) for x in rows], total, page, page_size)

@app.get('/api/public/gaceta/{document_id}')
def public_gaceta_detail(document_id: uuid.UUID, db: Session = Depends(get_db)):
    row = db.scalar(document_query(db, True).where(GacetaDocument.id == document_id))
    if row is None: raise HTTPException(404, 'Documento no encontrado')
    return document_response(row)

@app.get('/api/admin/gaceta')
def admin_gaceta(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), q: str | None = None, category: uuid.UUID | None = None, user: User = Depends(require_permission('gestion.gaceta.read')), db: Session = Depends(get_db)):
    query = document_query(db, False, q, category)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return paginate([document_response(x) for x in rows], total, page, page_size)

@app.get('/api/admin/gaceta/{document_id}')
def admin_gaceta_detail(document_id: uuid.UUID, user: User = Depends(require_permission('gestion.gaceta.read')), db: Session = Depends(get_db)):
    row = db.scalar(document_query(db).where(GacetaDocument.id == document_id))
    if row is None: raise HTTPException(404, 'Documento no encontrado')
    return document_response(row)

def save_document(*, db: Session, user: User, category_id: uuid.UUID, number: str, title: str, description: str | None, published_at: date, published: bool, pdf: UploadFile | None, row: GacetaDocument | None = None) -> GacetaDocument:
    category = db.get(GacetaCategory, category_id)
    if category is None:
        raise HTTPException(422, 'Categoría inexistente')
    # Regla de categoría inactiva:
    #  - Documento nuevo: solo se admiten categorías activas.
    #  - Documento existente: se puede conservar su categoría aunque esté inactiva.
    #  - Documento existente: cambiar a otra categoría exige que la nueva esté activa.
    if row is None:
        if not category.is_active:
            raise HTTPException(422, 'La categoría está inactiva; reactívela o elige otra')
    elif category.id != row.category_id and not category.is_active:
        raise HTTPException(422, 'La categoría está inactiva; reactívela o elige otra')
    if row is None:
        if pdf is None: raise HTTPException(422, 'El PDF es obligatorio')
        row = GacetaDocument(category_id=category_id, number=number.strip(), title=title.strip(), description=description, published_at=published_at, is_published=published, created_by_user_id=user.id, pdf=store_upload(pdf, 'pdf', user.id, db))
        db.add(row)
    else:
        row.category_id, row.number, row.title, row.description, row.published_at, row.is_published = category_id, number.strip(), title.strip(), description, published_at, published
        if pdf:
            previous_pdf = row.pdf
            row.pdf = store_upload(pdf, 'pdf', user.id, db)
            supersede_media(db, previous_pdf)
    db.commit(); db.refresh(row); return row

@app.post('/api/admin/gaceta')
def create_document(category_id: uuid.UUID = Form(...), number: str = Form(...), title: str = Form(...), description: str | None = Form(None), published_at: date = Form(...), is_published: bool = Form(False), pdf: UploadFile = File(...), user: User = Depends(require_permission('gestion.gaceta.manage')), db: Session = Depends(get_db)):
    return document_response(save_document(db=db, user=user, category_id=category_id, number=number, title=title, description=description, published_at=published_at, published=is_published, pdf=pdf))

@app.put('/api/admin/gaceta/{document_id}')
def update_document(document_id: uuid.UUID, category_id: uuid.UUID = Form(...), number: str = Form(...), title: str = Form(...), description: str | None = Form(None), published_at: date = Form(...), is_published: bool = Form(False), pdf: UploadFile | None = File(None), user: User = Depends(require_permission('gestion.gaceta.manage')), db: Session = Depends(get_db)):
    row = db.scalar(document_query(db).where(GacetaDocument.id == document_id))
    if row is None: raise HTTPException(404, 'Documento no encontrado')
    return document_response(save_document(db=db, user=user, category_id=category_id, number=number, title=title, description=description, published_at=published_at, published=is_published, pdf=pdf, row=row))

@app.delete('/api/admin/gaceta/{document_id}')
def delete_document(document_id: uuid.UUID, user: User = Depends(require_permission('gestion.gaceta.manage')), db: Session = Depends(get_db)):
    row = db.scalar(document_query(db).where(GacetaDocument.id == document_id))
    if row is None: raise HTTPException(404, 'Documento no encontrado')
    row.deleted_at = datetime.now(timezone.utc); row.is_published = False; db.commit(); return {'id': str(row.id), 'deleted': True}

@app.post('/api/admin/gaceta/{document_id}/{action}')
def publish_document(document_id: uuid.UUID, action: str, user: User = Depends(require_permission('gestion.gaceta.publish')), db: Session = Depends(get_db)):
    if action not in {'publish', 'unpublish'}: raise HTTPException(404, 'Acción no encontrada')
    row = db.scalar(document_query(db).where(GacetaDocument.id == document_id))
    if row is None: raise HTTPException(404, 'Documento no encontrado')
    row.is_published = action == 'publish'; db.commit(); return document_response(row)

def stream_media(media_id: uuid.UUID, db: Session):
    row = db.scalar(select(Media).where(Media.id == media_id, Media.is_active.is_(True)))
    if row is None: raise HTTPException(404, 'Archivo no encontrado')
    try: payload = get_storage_service().read(row.storage_path)
    except FileNotFoundError: raise HTTPException(404, 'Archivo no encontrado en storage')
    return Response(content=payload, media_type=row.mime_type, headers={'Content-Disposition': f'inline; filename="{row.original_filename}"'})

@app.get('/api/public/media/{media_id}')
def public_media(media_id: uuid.UUID, db: Session = Depends(get_db)):
    return stream_media(media_id, db)

@app.get('/api/admin/media')
def admin_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: str | None = None,
    q: str | None = None,
    is_active: bool | None = None,
    user: User = Depends(require_permission('gestion.media.read')),
    db: Session = Depends(get_db),
):
    query = select(Media)
    if kind:
        query = query.where(Media.kind == kind)
    if q:
        query = query.where(Media.original_filename.ilike(f'%{q}%'))
    if is_active is not None:
        query = query.where(Media.is_active.is_(is_active))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Media.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return paginate([media_admin_response(x) for x in rows], total, page, page_size)

@app.get('/api/admin/media/{media_id}')
def admin_media_detail(
    media_id: uuid.UUID,
    user: User = Depends(require_permission('gestion.media.read')),
    db: Session = Depends(get_db),
):
    row = db.get(Media, media_id)
    if row is None:
        raise HTTPException(404, 'Archivo no encontrado')
    return media_admin_response(row)

@app.post('/api/admin/media')
def admin_media_upload(
    file: UploadFile = File(...),
    kind: str = Form('image'),
    user: User = Depends(require_permission('gestion.media.upload')),
    db: Session = Depends(get_db),
):
    if kind not in {'image', 'pdf'}:
        raise HTTPException(422, 'Tipo de archivo inválido; use image o pdf')
    row = store_upload(file, kind, user.id, db)
    db.commit()
    db.refresh(row)
    return media_admin_response(row)

@app.delete('/api/admin/media/{media_id}')
def admin_media_deactivate(
    media_id: uuid.UUID,
    user: User = Depends(require_permission('gestion.media.manage')),
    db: Session = Depends(get_db),
):
    """Baja lógica de un archivo.

    Nunca se borra el binario del disco: la auditoría municipal requiere
    conservar el histórico. Si el archivo está en uso por un documento de
    Gaceta activo o por el alcalde vigente, se rechaza la operación.
    """
    row = db.get(Media, media_id)
    if row is None:
        raise HTTPException(404, 'Archivo no encontrado')
    if not row.is_active:
        return media_admin_response(row)
    document = db.scalar(
        select(GacetaDocument).where(
            GacetaDocument.pdf_media_id == media_id,
            GacetaDocument.deleted_at.is_(None),
        )
    )
    if document is not None:
        raise HTTPException(409, 'El archivo está asociado a un documento de Gaceta vigente')
    mayor = db.scalar(
        select(Mayor).where(
            Mayor.photo_media_id == media_id,
            Mayor.is_active.is_(True),
        )
    )
    if mayor is not None:
        raise HTTPException(409, 'El archivo está asociado al alcalde vigente')
    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return media_admin_response(row)

@app.get('/api/public/gaceta/{document_id}/pdf')
def public_pdf(document_id: uuid.UUID, db: Session = Depends(get_db)):
    row = db.scalar(document_query(db, True).where(GacetaDocument.id == document_id))
    if row is None: raise HTTPException(404, 'Documento no encontrado')
    return stream_media(row.pdf_media_id, db)

@app.get('/api/admin/users')
def list_users(user: User = Depends(require_permission('gestion.users.read')), db: Session = Depends(get_db)):
    return [user_response(db, x) for x in db.scalars(select(User).order_by(User.username)).all()]

@app.post('/api/admin/users')
def create_user(body: UserPayload, user: User = Depends(require_permission('gestion.users.manage')), db: Session = Depends(get_db)):
    from app.core.security import hash_password
    if not body.password: raise HTTPException(422, 'La contraseña es obligatoria')
    if db.scalar(select(User).where(User.username == body.username.strip().lower())): raise HTTPException(409, 'Usuario ya existente')
    # Asignar roles exige el permiso dedicado, igual que en Correspondencia.
    if body.role_ids:
        ensure_permission(db, user, 'gestion.roles.assign')
    row = User(username=body.username.strip().lower(), email=str(body.email) if body.email else None, password_hash=hash_password(body.password), is_active=body.is_active)
    for role_id in body.role_ids:
        role = db.get(Role, role_id)
        if role: row.roles.append(role)
    db.add(row); db.commit(); db.refresh(row); return user_response(db, row)

@app.put('/api/admin/users/{user_id}')
def update_user(user_id: uuid.UUID, body: UserPayload, user: User = Depends(require_permission('gestion.users.manage')), db: Session = Depends(get_db)):
    from app.core.security import hash_password
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(404, 'Usuario no encontrado')
    row.email, row.is_active = (str(body.email) if body.email else None), body.is_active
    if body.password:
        row.password_hash = hash_password(body.password)
    # 'role_ids' omitido no significa lista vacía: solo se reasigna si viene explícito
    # y el conjunto cambia realmente.
    if 'role_ids' in body.model_fields_set:
        requested = set(body.role_ids)
        current = {role.id for role in row.roles}
        if requested != current:
            ensure_permission(db, user, 'gestion.roles.assign')
        row.roles = [role for role in (db.get(Role, role_id) for role_id in body.role_ids) if role]
    db.commit(); db.refresh(row)
    return user_response(db, row)

@app.post('/api/admin/users/{user_id}/{action}')
def toggle_user(user_id: uuid.UUID, action: str, user: User = Depends(require_permission('gestion.users.manage')), db: Session = Depends(get_db)):
    if action not in {'activate', 'deactivate'}:
        raise HTTPException(404, 'Acción no encontrada')
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(404, 'Usuario no encontrado')
    row.is_active = action == 'activate'
    db.commit()
    return user_response(db, row)

@app.get('/api/admin/roles')
def list_roles(user: User = Depends(require_permission('gestion.roles.read')), db: Session = Depends(get_db)):
    return [{'id': str(x.id), 'code': x.code, 'name': x.name, 'description': x.description, 'is_active': x.is_active, 'permission_ids': [str(p.id) for p in x.permissions]} for x in db.scalars(select(Role).order_by(Role.code)).all()]

@app.get('/api/admin/permissions')
def list_permissions(user: User = Depends(require_permission('gestion.roles.read')), db: Session = Depends(get_db)):
    return [{'id': str(x.id), 'code': x.code, 'description': x.description} for x in db.scalars(select(Permission).order_by(Permission.code)).all()]

@app.post('/api/admin/roles')
def create_role(body: RolePayload, user: User = Depends(require_permission('gestion.roles.manage')), db: Session = Depends(get_db)):
    row = Role(code=body.code.strip(), name=body.name.strip(), description=body.description, is_active=body.is_active, permissions=[x for x in (db.get(Permission, item) for item in body.permission_ids) if x])
    db.add(row); db.commit(); db.refresh(row); return {'id': str(row.id), 'code': row.code, 'name': row.name, 'description': row.description, 'is_active': row.is_active, 'permission_ids': [str(x.id) for x in row.permissions]}

@app.put('/api/admin/roles/{role_id}')
def update_role(role_id: uuid.UUID, body: RolePayload, user: User = Depends(require_permission('gestion.roles.manage')), db: Session = Depends(get_db)):
    row = db.get(Role, role_id)
    if row is None:
        raise HTTPException(404, 'Rol no encontrado')
    row.code, row.name, row.description, row.is_active = body.code.strip(), body.name.strip(), body.description, body.is_active
    row.permissions = [x for x in (db.get(Permission, item) for item in body.permission_ids) if x]
    db.commit(); db.refresh(row)
    return {'id': str(row.id), 'code': row.code, 'name': row.name, 'description': row.description, 'is_active': row.is_active, 'permission_ids': [str(x.id) for x in row.permissions]}
