"""Live qualification controlled outside the model. Never trusts a model-written report."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import tempfile
import time
import urllib.request
import uuid

from task_tools import TaskTools


CSV = 'islem_id;tutar;durum\nA001;1250.50;tamamlandi\nA002;800.00;tamamlandi\nA003;450.00;iptal\nA004;1999.90;tamamlandi\nA005;0.00;tamamlandi\nA006;-200.00;iade\nA007;;tamamlandi\nA008;abc;tamamlandi\nA002;800.00;tamamlandi\n'
EDGE = 'islem_id;tutar;durum\nX001;abc;tamamlandi\nX001;99;tamamlandi\nX002;0;tamamlandi\nX003;-0.01;iade\nX004;NaN;tamamlandi\nX005;Infinity;tamamlandi\nX006;13.37;iptal\nX007;0.10;tamamlandi\nX008;0.20;tamamlandi\n'
KEYS = ('tamamlanan_islem_sayisi', 'tamamlanan_tutar', 'iade_tutari', 'net_satis',
        'iptal_sayisi', 'gecersiz_kayit_sayisi', 'yinelenen_kayit_sayisi')
EXPECTED = dict(zip(KEYS, (4, '4050.40', '-200.00', '3850.40', 1, 2, 1)))
EDGE_EXPECTED = dict(zip(KEYS, (3, '0.30', '-0.01', '0.29', 1, 3, 1)))
EMPTY_EXPECTED = dict(zip(KEYS, (0, '0.00', '0.00', '0.00', 0, 0, 0)))


def new_identity():
    return uuid.uuid4().hex[:12]


def atomic_json(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def http_client(base):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, payload=None, key=None):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        with opener.open(urllib.request.Request(base + path, data=data, headers=headers), timeout=10) as response:
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError('Sunucu yanıtı boyut sınırını aşıyor.')
            return json.loads(raw)
    return request


def qualify(root, base='http://127.0.0.1:5053', budget=900, fetch=None, log=print):
    root = Path(root).resolve()
    runtime = root / '.baris_runtime'
    runtime.mkdir(exist_ok=True)
    identity = new_identity()
    relative = 'baris_canli_kabul_' + identity
    directory = root / relative
    report_path = runtime / ('canli-kabul-' + identity + '.json')
    report = {'run_id': identity, 'passed': False, 'status': 'RUNNING',
              'started_at': time.time(), 'checks': [], 'jobs': [], 'commands': [],
              'transport': 'injected_test' if fetch is not None else 'local_http',
              'model_report_used_as_evidence': False, 'base': base}
    request = fetch or http_client(base)
    active = None
    def save():
        atomic_json(report_path, report)
    def check(name, expected, actual):
        passed = type(actual) is type(expected) and actual == expected
        report['checks'].append({'name': name, 'expected': expected, 'actual': actual, 'passed': passed})
        save()
        if not passed:
            raise ValueError('Kabul kontrolü kaldı: ' + name)
    def submit(message, expected):
        nonlocal active
        response = request('/api/tasks', {'message': message, 'expected_files': expected,
                                        'budget_seconds': budget}, identity + '-' + str(len(report['jobs'])))
        active = response['task_id']
        entry = {'task_id': active, 'model_metrics': []}
        report['jobs'].append(entry)
        save()
        deadline, cursor, last_log = time.monotonic() + budget + 30, 0, 0
        while time.monotonic() < deadline:
            job = request('/api/tasks/' + active + '?after=' + str(cursor))
            events = job.get('events', [])
            for event in events:
                cursor = max(cursor, event['seq'])
                if event['kind'] in {'MODEL_START', 'MODEL_DONE', 'MODEL_INTERRUPTED', 'MODEL_RETRY'}:
                    entry['model_metrics'].append(event)
            if time.monotonic() - last_log >= 15:
                log(f"{active}: {job['status']} • kullanılan {job.get('used', 0):.0f}/{budget} sn")
                last_log = time.monotonic()
            if job.get('result') is not None:
                entry['result'] = job['result']
                entry['used_seconds'] = job.get('used')
                result = job['result']
                active = None
                save()
                check('motor_dosyayi_dogruladi_' + str(len(report['jobs'])), True,
                      result.get('status') == 'VERIFIED' and result.get('verified') is True
                      and bool(result.get('execution_steps')) and result.get('acceptance', {}).get('success') is True)
                return result
            time.sleep(.1 if job.get('has_more') else 1)
        raise TimeoutError('Canlı kabul süresi doldu; yalnızca bu testin görevine iptal gönderilecek.')

    class Ledger:
        def update(self, job_id, **fields):
            report.update(fields)
            save()
    command_tools = None
    try:
        info = request('/api/engine_info')
        report['engine'] = info
        check('motor_surumu', 'local-ui-v10', info.get('build'))
        check('calisma_alani', str(root), info.get('workspace'))
        check('zamanlayici_hazir', True, info.get('scheduler_alive') is True)
        check('kuyruk_bos', True, not info.get('busy') and not info.get('queued') and not info.get('queue_blocked'))
        directory.mkdir(exist_ok=False)
        sentinel = directory / 'dokunma.txt'
        sentinel.write_bytes(('KORU-' + identity).encode())
        digest = hashlib.sha256(sentinel.read_bytes()).hexdigest()
        directory_identity = directory.stat().st_dev, directory.stat().st_ino
        def safe_directory():
            current = directory.stat()
            if directory.is_symlink() or (current.st_dev, current.st_ino) != directory_identity:
                raise ValueError('Kabul dizini değiştirilmiş; test durduruldu.')
        def create_input(name, content):
            safe_directory()
            with (directory / name).open('x', encoding='utf-8') as output:
                output.write(content)
        exact = 'Merhaba Barış | ' + identity
        target = relative + '/merhaba.txt'
        log('1/2: Birebir dosya yazma ve diskten bağımsız okuma.')
        submit(f'Yalnızca {relative} dizininde çalış. Dizin mevcut. {target} dosyasını '
               f'tam olarak {exact} içeriğiyle oluştur. Satır sonu ekleme. dokunma.txt dosyasını değiştirme.', {target: exact})
        safe_directory()
        check('utf8_birebir_icerik', exact, (directory / 'merhaba.txt').read_bytes().decode('utf-8'))
        check('ilk_gorev_koruma_dosyasi', digest, hashlib.sha256(sentinel.read_bytes()).hexdigest())
        marker = relative + '/hazir.txt'
        program = relative + '/analiz.py'
        log('2/2: Programı model yazacak; gizli girdilerle kontrolü dış test motoru yapacak.')
        result = submit(
            f'Yalnızca mevcut {relative} dizininde çalış. dokunma.txt ve merhaba.txt korunacak. '
            f'{program} oluştur. Komut arayüzü: python3 {program} GirdiCSV CiktiJSON. '
            'Yalnızca standart kütüphane; csv noktalı virgül, UTF-8. Başlık islem_id;tutar;durum. '
            'Decimal kullan. Her kimliğin yalnızca ilk satırını ele al; ilk satır geçersiz olsa da sonraki aynı kimlik yinelenendir. '
            'Boş, sayısal olmayan, NaN ve Infinity tutarları geçersiz say. '
            'tamamlandi tutarını ve sayısını topla; sıfır geçerli. Negatif iade tutarını topla; '
            'iptal satırını say ve nete katma. net=toplam+iade. JSON alanları: ' + ','.join(KEYS) + '. '
            'Para alanları tam iki ondalıklı metin. Boş veri başlıkla sıfır sonuç üretir. '
            'Eksik dosya, yanlış başlık veya aynı girdi/çıktı yolu: Türkçe hata, sıfırdan farklı çıkış; '
            'mevcut çıktıyı bozma. Sonucu atomik kaydet. Küçük bir deneme CSV oluşturup programı araçla gerçekten çalıştır. '
            f'Kod hazır olunca EN SON {marker} dosyasına tam olarak {identity} yaz. Rapor veya uzun açıklama yazma.', {marker: identity})
        safe_directory()
        check('ikinci_gorev_koruma_dosyasi', digest, hashlib.sha256(sentinel.read_bytes()).hexdigest())
        check('program_aracla_calistirildi', True, any(s.get('tool') == 'tool_run_shell' and s.get('success') is True
              and any(program in a for a in s.get('result', {}).get('argv', [])) for s in result.get('execution_steps', [])))
        source = directory / 'analiz.py'
        check('program_normal_dosya', True, source.is_file() and not source.is_symlink())
        report['program_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        command_tools = TaskTools(directory, Ledger(), identity, tool_seconds=15)
        def execute(input_name, output_name):
            safe_directory()
            command = ' '.join(shlex.quote(a) for a in ('python3', 'analiz.py', input_name, output_name))
            actual = command_tools.run_command(command)
            report['commands'].append(dict(command=command, **actual))
            save()
            return actual
        def read_json(name):
            path = directory / name
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or path.stat().st_size > 100_000:
                raise ValueError('Çıktı dosyası kapsam veya boyut sınırını aştı.')
            return json.loads(path.read_bytes())
        def successful_case(name, content, expected):
            input_name, output_name = name + '.csv', name + '.json'
            create_input(input_name, content)
            actual = execute(input_name, output_name)
            check(name + '_exit', 0, actual['process_exit_code'])
            check(name + '_komut_tamam', True, actual['success'])
            data = read_json(output_name)
            valid = isinstance(data, dict) and set(data) == set(expected) and all(
                type(data[k]) is type(v) and data[k] == v for k, v in expected.items())
            check(name + '_sonuc', expected, data if valid else {'gecersiz_sonuc': data})
        successful_case('normal', CSV, EXPECTED)
        successful_case('kenar', EDGE, EDGE_EXPECTED)
        successful_case('bos', 'islem_id;tutar;durum\n', EMPTY_EXPECTED)
        before = (directory / 'normal.json').read_bytes()
        create_input('bozuk.csv', 'yanlis;baslik\n')
        for name in ('olmayan.csv', 'bozuk.csv'):
            actual = execute(name, 'normal.json')
            check(name + '_hata_kodu', True, isinstance(actual['process_exit_code'], int) and actual['process_exit_code'] > 0)
            message = (actual['stderr'] + actual['stdout']).lower()
            check(name + '_turkce_hata', True, any(word in message for word in ('hata', 'bulunamad', 'okunamad', 'geçersiz')))
            check(name + '_cikti_korundu', True, (directory / 'normal.json').read_bytes() == before)
        input_before = (directory / 'normal.csv').read_bytes()
        actual = execute('normal.csv', 'normal.csv')
        check('ayni_yol_hata_kodu', True, isinstance(actual['process_exit_code'], int) and actual['process_exit_code'] > 0)
        check('girdi_korundu', True, (directory / 'normal.csv').read_bytes() == input_before)
        successful_case('tekrar', CSV, EXPECTED)
        check('koruma_dosyasi', digest, hashlib.sha256(sentinel.read_bytes()).hexdigest())
        check('program_test_sirasinda_degismedi', report['program_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        report.update(passed=True, status='PASSED')
    except (Exception, KeyboardInterrupt) as exc:
        report.update(passed=False, status='FAILED', error=type(exc).__name__ + ': ' + str(exc))
        if active:
            try:
                request('/api/tasks/' + active + '/cancel', {})
                report['cancel_requested_for'] = active
            except Exception as cancel_error:
                report['cancel_error'] = str(cancel_error)
    finally:
        if command_tools:
            command_tools.stop_child()
        report['finished_at'] = time.time()
        save()
    log(('CANLI KABUL GEÇTİ' if report['passed'] else 'CANLI KABUL KALDI') + ' • Rapor: ' + str(report_path))
    return report, report_path
