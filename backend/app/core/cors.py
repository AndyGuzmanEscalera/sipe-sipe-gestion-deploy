from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import Settings

def configure_cors(app: FastAPI, settings: Settings) -> None:
    origins = settings.cors_origins_list
    origin_regex = r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$' if settings.app_env == 'development' else None
    if origins or origin_regex:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_origin_regex=origin_regex, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
