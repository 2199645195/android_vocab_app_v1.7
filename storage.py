"""Versioned, validated local persistence. No network or UI dependencies."""
import io
import json
import math
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime

FILES = ('progress.json', 'wrong_words.jsonl', 'stats.json', 'custom_units.json',
         'review_schedule.json', 'study_activity.json', 'favorites.json',
         'card_schedule.json', 'word_details.json', 'learning_settings.json')
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 25 * 1024 * 1024
SETTINGS = {
    'mode': ['单词听音四选一', '中文释义', '词性判断', '综合测试'],
    'order': ['正序自动记录进度', '乱序随机练习'],
    'count': ['每天 10 个', '每天 15 个', '每天 20 个', '每天 25 个', '每天 30 个', '全部'],
}


def number(value, low=0, high=100000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('数值字段无效')


def word(value):
    if not isinstance(value, dict) or not isinstance(value.get('en'), str) or not value['en'].strip() or not isinstance(value.get('zh'), str):
        raise ValueError('单词结构无效')
    if not isinstance(value.get('pos', []), list) or any(not isinstance(p, str) for p in value.get('pos', [])):
        raise ValueError('词性须为字符串列表')
    if value.get('family') is not None and not isinstance(value['family'], str):
        raise ValueError('词族格式无效')


def validate(name, data):
    if name == 'wrong_words.jsonl':
        for item in data: word(item)
        return data
    if name == 'favorites.json':
        if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
            raise ValueError('收藏格式无效')
        return data
    if not isinstance(data, dict) or any(not isinstance(k, str) for k in data):
        raise ValueError(name + ' 须为对象')
    for key, value in data.items():
        if name in ('progress.json', 'stats.json'):
            number(value)
            if not isinstance(value, int): raise ValueError('计数须为整数')
        elif name == 'custom_units.json':
            if not isinstance(value, list): raise ValueError('单元须为列表')
            for item in value: word(item)
        elif name == 'learning_settings.json':
            if key in SETTINGS and value not in SETTINGS[key]: raise ValueError('学习设置无效')
            if key == 'unit' and not isinstance(value, str): raise ValueError('单元设置无效')
        else:
            if not isinstance(value, dict): raise ValueError('记录须为对象')
            if name in ('review_schedule.json', 'card_schedule.json'):
                word(value.get('word'))
                date.fromisoformat(value.get('due', ''))
                for field in ('wrong', 'correct', 'streak', 'level', 'repetitions', 'interval'):
                    if field in value:
                        number(value[field], high=36500 if field == 'interval' else 100000000)
                        if not isinstance(value[field], int): raise ValueError('复习计数须为整数')
                if 'level' in value: number(value['level'], high=6)
                if 'ease' in value: number(value['ease'], 1.3, 3.0)
            elif name == 'study_activity.json':
                date.fromisoformat(key)
                for field in ('answered', 'correct', 'wrong', 'cards', 'cards_known'):
                    if field in value:
                        number(value[field])
                        if not isinstance(value[field], int): raise ValueError('学习计数须为整数')
                if not isinstance(value.get('unique', []), list) or any(not isinstance(x, str) for x in value.get('unique', [])):
                    raise ValueError('学习单词须为字符串列表')
            elif name == 'word_details.json':
                if not isinstance(value.get('manual_fields', []), list) or any(not isinstance(x, str) for x in value.get('manual_fields', [])):
                    raise ValueError('手动编辑字段无效')
                for field in ('ipa', 'example', 'example_zh', 'phrases', 'source'):
                    if field in value and not isinstance(value[field], str): raise ValueError('词典资料须为文本')
    return data


def decode(name, content):
    text = content.decode('utf-8-sig')
    data = ([json.loads(line) for line in text.splitlines() if line.strip()]
            if name.endswith('.jsonl') else json.loads(text))
    return validate(name, data)


def atomic_write(path, content):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.vocab-', dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def backup(data_dir):
    buffer = io.BytesIO()
    present = [name for name in FILES if os.path.isfile(os.path.join(data_dir, name))]
    total = 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in present:
            with open(os.path.join(data_dir, name), 'rb') as stream: content = stream.read(MAX_FILE + 1)
            total += len(content)
            if len(content) > MAX_FILE or total > MAX_TOTAL: raise ValueError('备份数据过大')
            decode(name, content)
            archive.writestr(name, content)
        archive.writestr('manifest.json', json.dumps({'format': 'vocabtrainer-v17', 'files': present,
                          'created': datetime.now().isoformat()}))
    return buffer.getvalue()


def read_backup(payload):
    if len(payload) > MAX_TOTAL: raise ValueError('ZIP 体积过大')
    pending = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len(names) > len(FILES) + 1: raise ValueError('重复或过多文件')
        if 'manifest.json' not in names: raise ValueError('缺少备份清单')
        if sum(info.file_size for info in infos) > MAX_TOTAL: raise ValueError('解压后数据过大')
        for info in infos:
            if info.filename not in FILES + ('manifest.json',) or info.is_dir() or info.file_size > MAX_FILE or info.flag_bits & 1:
                raise ValueError('非法、加密或过大文件')
        manifest = json.loads(archive.read('manifest.json').decode('utf-8-sig'))
        if not isinstance(manifest, dict) or manifest.get('format') not in ('vocabtrainer-v14', 'vocabtrainer-v17'):
            raise ValueError('备份版本不支持')
        listed = manifest.get('files')
        if not isinstance(listed, list) or any(not isinstance(n, str) or n not in FILES for n in listed) or len(listed) != len(set(listed)):
            raise ValueError('备份清单无效')
        actual = set(names) - {'manifest.json'}
        if not actual.issubset(set(listed)) or (manifest['format'] == 'vocabtrainer-v17' and actual != set(listed)):
            raise ValueError('备份清单与文件不一致')
        for name in actual:
            content = archive.read(name)
            decode(name, content)
            pending[name] = content
    if not pending: raise ValueError('备份没有学习数据')
    return pending


def restore(data_dir, payload):
    pending = read_backup(payload)  # Validate every record before any mutation.
    os.makedirs(data_dir, exist_ok=True)
    recovery = os.path.join(data_dir, 'before_restore.zip')
    # Preserve the exact original bytes, even if old files contain damaged JSON.
    buffer = io.BytesIO()
    present = [n for n in FILES if os.path.isfile(os.path.join(data_dir, n))]
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in present: archive.write(os.path.join(data_dir, name), name)
        archive.writestr('manifest.json', json.dumps({'format': 'vocabtrainer-v17', 'files': present}))
    atomic_write(recovery, buffer.getvalue())
    stage = tempfile.mkdtemp(prefix='.restore-', dir=data_dir)
    committed = []
    try:
        for name, content in pending.items():
            atomic_write(os.path.join(stage, name), content)
            target = os.path.join(data_dir, name)
            if os.path.isfile(target): shutil.copy2(target, os.path.join(stage, name + '.old'))
        try:
            for name in pending:
                os.replace(os.path.join(stage, name), os.path.join(data_dir, name))
                committed.append(name)
        except OSError:
            for name in reversed(committed):
                old = os.path.join(stage, name + '.old')
                target = os.path.join(data_dir, name)
                if os.path.exists(old): os.replace(old, target)
                else: os.unlink(target)
            raise
    finally:
        shutil.rmtree(stage)
    return len(pending)
