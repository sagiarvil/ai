"""Loopback Host validation and a bounded ASGI body before JSON is parsed."""
import asyncio
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class LocalHttpGuard:
    def __init__(self, app, max_bytes=262144, body_seconds=10):
        self.app, self.max_bytes, self.body_seconds = app, max_bytes, body_seconds

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def reject(code, message):
            await JSONResponse({'detail': message}, status_code=code)(scope, receive, send)
        headers = scope.get('headers', [])
        hosts = [v.decode('latin1') for k, v in headers if k.lower() == b'host']
        try:
            authority = urlsplit('http://' + hosts[0]) if len(hosts) == 1 else None
            valid = (authority is not None and authority.hostname in {'127.0.0.1', 'localhost', '::1'}
                     and authority.username is None and authority.password is None
                     and not authority.path and not authority.query and not authority.fragment)
            if authority and authority.port is not None:
                valid = valid and 1 <= authority.port <= 65535
        except (ValueError, IndexError):
            valid = False
        if not valid:
            return await reject(400, 'Yalnızca yerel sunucu adresine izin verilir.')
        lengths = [v for k, v in headers if k.lower() == b'content-length']
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                return await reject(400, 'Geçersiz istek uzunluğu.')
            if int(lengths[0]) > self.max_bytes:
                return await reject(413, 'İstek 256 KiB boyut sınırını aşıyor.')
        body = bytearray()
        try:
            async with asyncio.timeout(self.body_seconds):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    body.extend(message.get('body', b''))
                    if len(body) > self.max_bytes:
                        return await reject(413, 'İstek 256 KiB boyut sınırını aşıyor.')
                    if not message.get('more_body', False):
                        break
        except TimeoutError:
            return await reject(408, 'İstek gövdesi zamanında alınamadı.')
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, bounded_receive, send)
