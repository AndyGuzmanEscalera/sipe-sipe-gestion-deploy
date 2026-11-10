import logging
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

class SafeErrorMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = False
        async def tracked(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        try:
            await self.app(scope, receive, tracked)
        except Exception:
            logger.exception('Unhandled request error')
            if started:
                raise
            await JSONResponse(status_code=500, content={'detail': 'Error del servidor. Intente nuevamente.'})(scope, receive, send)
