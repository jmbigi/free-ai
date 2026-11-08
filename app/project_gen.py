"""Project generator: uses the gateway's own routing (ForthTrade IA) to generate
multi-file project scaffolds, extracts `### FILE:` blocks, retries with backoff,
and stores evidence. Designed for free-tier limits (honest, not unlimited).
"""
from __future__ import annotations
import asyncio, json, os, re, shutil, tempfile, time
from pathlib import Path
from typing import Any
from .router import execute_with_fallback
from .config import settings

FILE_RE = re.compile(
    r'(?:^|\n)(?:### FILE:|## Archivo(?: \d+)?:|\*\*FILE:\*?\*?)\s*`?([^`\n]+?)`?\s*\*?\*?\s*\n```[^\n]*\n(.*?)```',
    re.S,
)


def _safe_rel(path: str) -> str | None:
    rel = path.strip().replace('\\', '/').lstrip('/')
    p = Path(rel)
    if not rel or rel.startswith('/') or '..' in p.parts or any(c in rel for c in ['\x00']):
        return None
    return rel


def extract_files(text: str) -> list[dict[str, str]]:
    out = []
    seen = set()
    for m in FILE_RE.finditer(text or ''):
        rel = _safe_rel(m.group(1))
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append({'path': rel, 'content': m.group(2).rstrip() + '\n'})
    return out


async def generate_one(*, prompt: str, name: str, model: str = 'auto', max_tokens: int = 1800,
                       temperature: float = 0, max_retries: int = 2, retry_delay_s: float = 55.0,
                       keep_temp: bool = False) -> dict[str, Any]:
    base = Path(tempfile.mkdtemp(prefix='ft-ia-project-', dir='/tmp/kilo'))
    try:
        os.chmod(base, 0o700)
    except Exception:
        pass
    outdir = base / (re.sub(r'[^a-zA-Z0-9._-]+', '-', name)[:80] or 'project')
    outdir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        'name': name, 'ts': int(time.time()), 'ok': False, 'attempts_meta': [],
        'model_requested': model, 'files_extracted': 0, 'temp_dir': str(base),
        'honest_note': 'Generated via ForthTrade IA gateway routing (FREE_ONLY). Free upstreams have quotas/rate limits/capacity; output must be reviewed/tested.',
    }
    system = (
        'You are a senior software engineer. Generate correct, production-minded, honest code/design. '
        'Declare dependencies and limitations. Return files using this exact format for every file:\n'
        '### FILE: relative/path.ext\n```lang\n<content>\n```\n'
        'Do not use absolute paths or "..". Keep code coherent and minimal but complete for the requested scope.'
    )
    payload = {
        'model': model, 'temperature': temperature, 'max_tokens': max_tokens,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
        'stream': False, 'gateway': {'max_retries': int(getattr(settings, 'default_max_retries', 4) or 4)},
    }
    content = ''
    last_detail = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            data, attempts = await execute_with_fallback(dict(payload))
            g = data.get('gateway') or {}
            msg = ((data.get('choices') or [{}])[0].get('message') or {})
            content = msg.get('content') or ''
            ok = bool(content and not data.get('detail') and not data.get('error'))
            meta = {'attempt': attempt, 'ok': ok, 'selected': g.get('selected') or data.get('model'),
                    'gateway_attempts': len(attempts or g.get('attempts') or []), 'fallback_used': g.get('fallback_used')}
            evidence['attempts_meta'].append(meta)
            evidence['selected'] = meta['selected']
            evidence['last_gateway'] = g
            if ok:
                evidence['ok'] = True
                break
            last_detail = data.get('detail') or data.get('error') or 'empty content'
        except Exception as e:
            last_detail = {'message': str(e)[:500], 'attempts': getattr(e, 'attempts', None)}
            evidence['attempts_meta'].append({'attempt': attempt, 'ok': False, 'error': str(e)[:300]})
        if attempt < max_retries:
            await asyncio.sleep(max(1.0, min(180.0, retry_delay_s)))
    evidence['detail'] = last_detail
    (outdir / 'GENERATED.txt').write_text(content or '')
    files = extract_files(content)
    for f in files:
        fp = outdir / f['path']
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f['content'])
    evidence['files_extracted'] = len(files)
    evidence['files'] = [f['path'] for f in files]
    evidence['generated_chars'] = len(content or '')
    (outdir / '_meta.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    # return summary + limited content; optionally cleanup
    summary = {k: v for k, v in evidence.items() if k not in ('last_gateway',)}
    summary['output_dir'] = str(outdir)
    summary['files'] = evidence['files']
    summary['content_preview'] = (content or '')[:4000]
    if not keep_temp:
        try:
            shutil.rmtree(base)
            summary['output_dir'] = '(deleted temporary directory)'
            summary['temp_deleted'] = True
        except Exception as e:
            summary['temp_delete_error'] = str(e)[:200]
    return summary
