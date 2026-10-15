"""Optional embeddings; the CLI imports only standard-library modules here."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys

SKILL = Path(__file__).resolve().parent.parent
CACHE = Path.home() / '.cache' / 'agent-work-log' / 'models'
DEFAULT_MODEL = 'BAAI/bge-small-zh-v1.5'
FASTEMBED_VERSION = '0.9.0'

# P1's query coverage and duplicate Jaccard cutoffs, preserved for every backend.
LEX_THRESHOLD = 0.5
JACCARD_THRESHOLD = 0.6
# Fake values are fixed by SPEC, independent of the real model calibration.
FAKE_SEM_THRESHOLD = 0.8
FAKE_SEM_FLOOR = 0.5
FAKE_DEDUP_SEM_THRESHOLD = 0.95
# Sweep every cosine breakpoint on the unmodified 12 lexical / 8 paraphrase /
# 4 negative queries, rejecting any forbidden result. All three models peak at
# 5/8 paraphrases. Use the midpoint of each model's full feasible interval;
# never tune by query text or fixture ID. Floor=0.3 is fixed across candidates
# to clip low background similarity; it changes ranking, not the hit condition.
LOCAL_SEM_THRESHOLD = 0.5918346982657758  # BGE: (0.5815737156, 0.6020956810]
LOCAL_SEM_FLOOR = 0.3
# Conservative near-identity cutoff; not estimated from the eight recall cases.
LOCAL_DEDUP_SEM_THRESHOLD = 0.95
LOCAL_MODEL_THRESHOLDS = {
    'BAAI/bge-small-zh-v1.5': LOCAL_SEM_THRESHOLD,
    # MiniLM: (0.4686143919, 0.5200289739]
    'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2': 0.49432168288223577,
    # potion: (0.3795458399, 0.3882860402]
    'minishlab/potion-multilingual-128M': 0.38391594003677865,
}


class Unavailable(ValueError):
    pass


def selected_model():
    override = os.environ.get('AGENT_WORK_LOG_EMBED_MODEL')
    if override:
        return override
    config = CACHE / 'selected.json'
    return json.loads(config.read_text(encoding='utf-8'))['model'] if config.exists() else DEFAULT_MODEL


def interpreter():
    return Path(os.environ.get('AGENT_WORK_LOG_EMBED_PYTHON', str(SKILL / '.venv' / 'bin' / 'python')))


def manifest(model):
    path = CACHE / ('model-' + hashlib.sha256(model.encode()).hexdigest() + '.json')
    return json.loads(path.read_text(encoding='utf-8'))


def cosine(a, b):
    if len(a) != len(b):
        raise Unavailable('向量维数不一致')
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return max(-1., min(1., sum(x*y for x, y in zip(a, b)) / norm)) if norm else 0.


def validate(vectors, count):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise Unavailable('后端返回的向量数量不正确')
    dimensions = set()
    for vector in vectors:
        if not isinstance(vector, list) or not vector or any(
                not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
            raise Unavailable('后端返回无效向量')
        dimensions.add(len(vector))
    if len(dimensions) > 1:
        raise Unavailable('向量维数不一致')
    return vectors


class Backend:
    def __init__(self, mode):
        self.kind = 'fake' if mode.startswith('fake:') else 'local'
        if self.kind == 'fake':
            self.path = Path(mode[5:])
            data = self.path.read_bytes()
            self.mapping = json.loads(data)
            validate(list(self.mapping.values()), len(self.mapping))
            self.dim = len(next(iter(self.mapping.values()))) if self.mapping else 256
            self.model_id = 'fake@' + hashlib.sha256(data).hexdigest() + ':v1'
            self.threshold, self.floor, self.dedup_threshold = (
                FAKE_SEM_THRESHOLD, FAKE_SEM_FLOOR, FAKE_DEDUP_SEM_THRESHOLD)
        else:
            self.python = interpreter()
            if not self.python.is_file():
                raise Unavailable(f'解释器不存在：{self.python}')
            self.model = selected_model()
            info = manifest(self.model)
            for item in info['files']:
                path = Path(info['path']) / item['path']
                if not path.is_file() or path.stat().st_size != item['size']:
                    raise Unavailable('本地模型文件缺失或变化，请运行 embed-setup')
            self.model_id = info['model_id']
            self.threshold, self.floor, self.dedup_threshold = (
                LOCAL_MODEL_THRESHOLDS.get(self.model, LOCAL_SEM_THRESHOLD),
                LOCAL_SEM_FLOOR, LOCAL_DEDUP_SEM_THRESHOLD)

    def embed(self, role, texts):
        if self.kind == 'fake':
            with Path(str(self.path) + '.calls').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(texts, ensure_ascii=False) + '\n')
            result = []
            for text in texts:
                if text in self.mapping:
                    vector = self.mapping[text]
                else:
                    rng = random.Random(hashlib.sha256(text.encode()).digest())
                    vector = [rng.uniform(-1., 1.) for _ in range(self.dim)]
                    length = math.sqrt(sum(x*x for x in vector))
                    vector = [x/length for x in vector]
                result.append(vector)
        else:
            process = subprocess.run([str(self.python), str(SKILL / 'scripts' / 'embed_worker.py')],
                                     input=json.dumps(dict(model=self.model, role=role, texts=texts)),
                                     text=True, capture_output=True)
            if process.returncode:
                # Keep the contract's one-line warning even for multiline library errors.
                raise Unavailable(' '.join(process.stderr.splitlines()) or 'worker 运行失败')
            response = json.loads(process.stdout)
            if response['model_id'] != self.model_id:
                raise Unavailable('worker 模型标识不一致')
            result = response['vectors']
        return validate(result, len(texts))


def fallback(mode, exc):
    if mode == 'local':
        print('embedding 不可用，已回退词项检索：' + ' '.join(str(exc).splitlines()), file=sys.stderr)


def get_backend(mode=None):
    mode = mode or os.environ.get('AGENT_WORK_LOG_EMBED', 'auto')
    if mode == 'none':
        return None
    if mode not in ('auto', 'local') and not mode.startswith('fake:'):
        raise ValueError('AGENT_WORK_LOG_EMBED 应为 auto、none、local 或 fake:<路径>')
    try:
        return Backend(mode)
    except (OSError, ValueError, KeyError) as exc:
        fallback(mode, exc)
        return None


class VectorCache:
    def __init__(self, path, backend):
        self.path, self.backend = path, backend

    def vectors(self, role, texts):
        unique = list(dict.fromkeys(texts))
        keys = {text: hashlib.sha256(text.encode()).hexdigest() for text in unique}
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS vectors (
                model_id TEXT, role TEXT, text_sha256 TEXT, vector TEXT NOT NULL,
                PRIMARY KEY(model_id, role, text_sha256))''')
            found = {}
            for text in unique:
                row = db.execute('SELECT vector FROM vectors WHERE model_id=? AND role=? AND text_sha256=?',
                                 (self.backend.model_id, role, keys[text])).fetchone()
                if row:
                    found[text] = json.loads(row[0])
            missing = [text for text in unique if text not in found]
            if missing:
                vectors = self.backend.embed(role, missing)
                for text, vector in zip(missing, vectors):
                    db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)',
                               (self.backend.model_id, role, keys[text], json.dumps(vector)))
                    found[text] = vector
            db.commit()
        return [found[text] for text in texts]


def setup(args):
    uv = shutil.which('uv')
    if not uv:
        raise ValueError('未找到 uv，请先安装 uv')
    python = SKILL / '.venv' / 'bin' / 'python'
    commands = [[uv, 'venv', str(SKILL / '.venv')]] if not python.exists() else []
    commands += [[uv, 'pip', 'install', '--python', str(python), f'fastembed=={FASTEMBED_VERSION}'],
                 [str(python), str(SKILL / 'scripts' / 'embed_worker.py'), '--setup', args.model]]
    for command in commands:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise ValueError('模型安装失败：' + result.stderr)
        if command == commands[-1]:
            info = json.loads(result.stdout)
        elif result.stderr:
            print(result.stderr, end='', file=sys.stderr)
    (CACHE / 'selected.json').write_text(json.dumps(dict(model=args.model)), encoding='utf-8')
    value = dict(model_id=info['model_id'], cache=str(CACHE))
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def status(args):
    mode = os.environ.get('AGENT_WORK_LOG_EMBED', 'auto')
    backend = get_backend(mode)
    reason = None
    available = backend is not None
    if backend:
        try:
            backend.embed('query', ['本地模型可用性检查'])
        except (OSError, ValueError, KeyError) as exc:
            available, reason = False, str(exc)
    value = dict(backend=mode, model_id=backend.model_id if backend else None,
                 available=available, cache=str(CACHE))
    if reason:
        value['reason'] = reason
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def register(subparsers, helpers):
    for name, function in [('embed-setup', setup), ('embed-status', status)]:
        parser = subparsers.add_parser(name, help='安装本地向量模型' if name == 'embed-setup' else '查看本地向量模型状态')
        helpers.add_location(parser)
        parser.add_argument('--json', action='store_true')
        if name == 'embed-setup':
            parser.add_argument('--model', default=DEFAULT_MODEL)
        parser.set_defaults(func=function)
