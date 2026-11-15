"""Temporary local UI runner for the A/B day-two walkthrough, never production.

Run on a separate loopback-published port. Only production business time is
simulated; authentication, OAuth and journal validation remain in force.
"""
import argparse
from datetime import datetime, timedelta
from unittest.mock import patch
import uvicorn
from starlette.responses import JSONResponse
from app.core.database import engine
from app.modules.production import release_service, run_service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-walkthrough', action='store_true', required=True)
    parser.parse_args()
    if engine.url.host != 'mysql':
        raise RuntimeError('Only the local compose database is supported.')
    def now():
        return (datetime.now(run_service.ZONE) + timedelta(days=1)).replace(tzinfo=None, microsecond=0)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = now().replace(tzinfo=run_service.ZONE)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    print('SYNTHETIC A/B WALKTHROUGH CLOCK: real business time plus one day', flush=True)
    with patch.object(release_service, 'now', now), patch.object(run_service, 'datetime', Clock):
        from app.main import app

        async def local_port_adapter(scope, receive, send):
            # The production middleware remains unchanged. Admit only this
            # loopback test origin and normalize its separate port internally.
            if scope['type'] == 'http':
                headers = dict(scope['headers'])
                if headers.get(b'host') != b'localhost:8001' or headers.get(b'origin', b'http://localhost:8001') != b'http://localhost:8001':
                    return await JSONResponse({'detail': 'Local walkthrough origin required'}, 403)(scope, receive, send)
                scope = {**scope, 'headers': [(key, b'localhost:8000' if key == b'host' else b'http://localhost:8000' if key == b'origin' else value)
                                             for key, value in scope['headers']]}
            await app(scope, receive, send)

        uvicorn.run(local_port_adapter, host='0.0.0.0', port=8000, access_log=False)


if __name__ == '__main__':
    main()
