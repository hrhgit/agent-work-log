"""Isolated fastembed process. Only --setup is allowed to access the network."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

CACHE = Path.home() / '.cache' / 'agent-work-log' / 'models'
PROTOCOL = 'worklog-embedding-v1'


def manifest_path(model):
    return CACHE / ('model-' + hashlib.sha256(model.encode()).hexdigest() + '.json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--setup', metavar='MODEL')
    args = parser.parse_args()
    if not args.setup:
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        # Defense in depth: even a library regression must not send log text out.
        import socket
        def offline(*args, **kwargs):
            raise OSError('embedding worker 禁止网络访问')
        socket.socket.connect = offline
        socket.socket.connect_ex = offline
        socket.create_connection = offline
    with redirect_stdout(sys.stderr):
        from fastembed import TextEmbedding
        if args.setup:
            model = TextEmbedding(model_name=args.setup, cache_dir=str(CACHE), threads=2,
                                  providers=['CPUExecutionProvider'])
            # Force loading and validate inference before declaring installation ready.
            list(model.embed(['本地模型安装检查']))
            folder = Path(model.model._model_dir).resolve()
            files = []
            digest = hashlib.sha256()
            for path in sorted(folder.rglob('*')):
                if not path.is_file() or '.cache' in path.relative_to(folder).parts:
                    continue
                relative = path.relative_to(folder).as_posix()
                digest.update(relative.encode())
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                files.append({'path': relative, 'size': path.stat().st_size})
            version = importlib.metadata.version('fastembed')
            info = dict(model=args.setup, model_id=f'{args.setup}@{digest.hexdigest()}:fastembed-{version}:{PROTOCOL}',
                        path=str(folder), files=files, fastembed=version)
            target = manifest_path(args.setup)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            request = json.load(sys.stdin)
            name, role, texts = request['model'], request['role'], request['texts']
            if role not in ('query', 'passage') or not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                raise ValueError('请求须含 role=query|passage 和 texts 字符串数组')
            info = json.loads(manifest_path(name).read_text(encoding='utf-8'))
            if info['fastembed'] != importlib.metadata.version('fastembed'):
                raise ValueError('fastembed 版本变化，请重新运行 embed-setup')
            model = TextEmbedding(model_name=name, cache_dir=str(CACHE), threads=2,
                                  providers=['CPUExecutionProvider'], local_files_only=True,
                                  specific_model_path=info['path'])
            # Fastembed's supported BGE-zh, MiniLM and potion models need no prefix.
            # e5 requires these prefixes for every language, including Chinese.
            if 'e5' in name.lower():
                texts = [('query: ' if role == 'query' else 'passage: ') + text for text in texts]
                vectors = list(model.embed(texts))
            else:
                vectors = list((model.query_embed if role == 'query' else model.passage_embed)(texts))
            info = dict(model_id=info['model_id'], vectors=[v.tolist() for v in vectors])
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'embedding worker: {exc}', file=sys.stderr)
        raise SystemExit(1)
