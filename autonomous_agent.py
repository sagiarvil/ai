#!/usr/bin/env python3
"""Terminal client of the same durable runtime used by the local application."""
import argparse
import json
from pathlib import Path
import time
import uuid

from live_qualification import http_client


def main():
    parser = argparse.ArgumentParser(description='Barış AI yerel görev istemcisi')
    parser.add_argument('message', help='Uygulanacak talimat')
    parser.add_argument('--port', type=int, default=5053)
    parser.add_argument('--budget', type=int, default=900, choices=range(30, 1801), metavar='30..1800')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port 1024–65535 arasında olmalı.')
    request = http_client(f'http://127.0.0.1:{args.port}')
    task_id = None
    try:
        info = request('/api/engine_info')
        if (info.get('build') != 'local-ui-v9' or
                info.get('source_root') != str(Path(__file__).resolve().parent)):
            raise ValueError('İstemci ve yerel sunucu sürümü veya kaynağı uyuşmuyor.')
        job = request('/api/tasks', {'message': args.message, 'budget_seconds': args.budget}, uuid.uuid4().hex)
        task_id = job['task_id']
        print('Görev kaydedildi:', task_id, flush=True)
        deadline, cursor = time.monotonic() + args.budget + 60, 0
        while time.monotonic() < deadline:
            job = request('/api/tasks/' + task_id + '?after=' + str(cursor))
            for event in job.get('events', []):
                cursor = max(cursor, event['seq'])
                if event.get('data', {}).get('message'):
                    print(event['data']['message'], flush=True)
            if job.get('result') is not None:
                print(json.dumps(job['result'], ensure_ascii=False, indent=2))
                return 0 if job['result'].get('verified') is True else 2
            time.sleep(.1 if job.get('has_more') else 1)
        print('İzleme süresi doldu; görev tekrar gönderilmedi. Görev:', task_id)
        return 2
    except KeyboardInterrupt:
        if task_id:
            request('/api/tasks/' + task_id + '/cancel', {})
        print('Durdurma isteği kaydedildi.')
        return 130
    except Exception as exc:
        print('Görev doğrulanamadı:', str(exc))
        if task_id:
            print('Kayıt korundu; yeniden gönderilmedi. Görev:', task_id)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
