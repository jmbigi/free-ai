"""Project generator: uses the gateway's own routing (ForthTrade IA) to generate
multi-file project scaffolds, extracts `### FILE:` blocks, retries with backoff,
and stores evidence. Designed for free-tier limits (honest, not unlimited).
"""
from __future__ import annotations
import ast, asyncio, json, os, re, shutil, tempfile, time
from pathlib import Path
from typing import Any
from .router import execute_with_fallback
from .config import settings

FILE_RE = re.compile(
    r'(?:^|\n)(?:### FILE:|## (?:Archivo|File)(?: \d+)?:|\*\*FILE:\*?\*?)\s*`?([^`\n]+?)`?\s*\*?\*?\s*\n```[^\n]*\n(.*?)```',
    re.S,
)
MAX_FILES = 40
MAX_FILE_BYTES = 200_000


def _safe_rel(path: str) -> str | None:
    rel = (path or '').strip().replace('\\', '/').lstrip('/')
    rel = rel.split()[0] if rel else rel  # tolerate "path (note)"
    p = Path(rel)
    if not rel or rel.startswith('/') or '..' in p.parts or any(c in rel for c in ['\x00', '\r', '\n']):
        return None
    if len(rel) > 240:
        return None
    return rel


def extract_files(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in FILE_RE.finditer(text or ''):
        rel = _safe_rel(m.group(1))
        if not rel or rel in seen:
            continue
        body = m.group(2)
        if len(body.encode('utf-8', 'ignore')) > MAX_FILE_BYTES:
            body = body[:MAX_FILE_BYTES] + '\n# ... truncated by gateway safety limit ...'
        seen.add(rel)
        out.append({'path': rel, 'content': body.rstrip() + '\n'})
        if len(out) >= MAX_FILES:
            break
    return out


_LOG_FMT_RE = re.compile(r'logger\.(debug|info|warning|error|exception|critical)\s*\(([^)]{0,400})\)')

def _quality_notes(files: list[dict[str, str]]) -> list[dict[str, Any]]:
    notes = []
    for f in files:
        if f['path'].endswith('.py'):
            try:
                ast.parse(f['content'])
                notes.append({'path': f['path'], 'check': 'python_ast', 'ok': True})
            except Exception as e:
                notes.append({'path': f['path'], 'check': 'python_ast', 'ok': False, 'error': str(e)[:220]})
            # heuristic: %d with common non-int identifiers
            for m in _LOG_FMT_RE.finditer(f['content']):
                call = m.group(2)
                if '%d' in call and re.search(r'\b(token|uuid|idempot|request_id|trace_id|saga_id|corr|key|name|msg|message)\b', call, re.I) and '%s' not in call.split('%d')[0][-20:]:
                    notes.append({'path': f['path'], 'check': 'logging_format_heuristic', 'ok': False,
                                  'warning': 'Possible %d used for non-int value (e.g. token/UUID/str). Prefer %s or f-string.', 'sample': call[:180]})
                    break
        elif f['path'].endswith('.json'):
            try:
                json.loads(f['content'])
                notes.append({'path': f['path'], 'check': 'json', 'ok': True})
            except Exception as e:
                notes.append({'path': f['path'], 'check': 'json', 'ok': False, 'error': str(e)[:220]})
    return notes


async def generate_one(*, prompt: str, name: str, model: str = 'auto', max_tokens: int = 1800,
                       temperature: float = 0, max_retries: int = 2, retry_delay_s: float = 55.0,
                       keep_temp: bool = False) -> dict[str, Any]:
    base_parent = Path('/tmp/kilo'); base_parent.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix='ft-ia-project-', dir=str(base_parent)))
    try:
        os.chmod(base, 0o700)
    except Exception:
        pass
    safe_name = re.sub(r'[^a-zA-Z0-9._-]+', '-', (name or 'project').strip())[:80] or 'project'
    outdir = base / safe_name
    outdir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        'name': safe_name, 'ts': int(time.time()), 'ok': False, 'attempts_meta': [],
        'model_requested': model, 'files_extracted': 0, 'temp_dir': str(base),
        'honest_note': 'Generated via ForthTrade IA gateway routing (FREE_ONLY). Free upstreams have quotas/rate limits/capacity; output must be reviewed and tested locally.',
    }
    system = (
        'You are a senior software engineer. Generate correct, production-minded, honest code/design. '
        'Declare dependencies and limitations. Return files using this exact format for every file:\n'
        '### FILE: relative/path.ext\n```lang\n<content>\n```\n'
        'Rules: no absolute paths, no "..", include README/tests when useful, keep code coherent and runnable where possible. '
        'Quality: match placeholders to types (logging `%d` only for real ints; use `%s` for UUID/str/objects), handle errors explicitly, '
        'avoid hidden mutable defaults, make retries/idempotency deterministic in simulations, and prefer simple testable interfaces.'
    )
    payload = {
        'model': model, 'temperature': temperature, 'max_tokens': max(256, min(4000, max_tokens)),
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
        'stream': False, 'gateway': {'max_retries': int(getattr(settings, 'default_max_retries', 4) or 4)},
    }
    content = ''
    last_detail = None
    for attempt in range(1, max(1, min(4, max_retries)) + 1):
        try:
            data, attempts = await execute_with_fallback(dict(payload))
            g = data.get('gateway') or {}
            msg = ((data.get('choices') or [{}])[0].get('message') or {})
            content = msg.get('content') or ''
            if not content and not msg.get('tool_calls'): content = msg.get('reasoning') or msg.get('reasoning_content') or ''
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
            # adaptive backoff: longer after rate/limit signals
            delay = retry_delay_s
            s = json.dumps(last_detail, ensure_ascii=False).lower() if last_detail else ''
            if any(x in s for x in ['429', 'rate limit', 'free limit', 'every 45', 'cooldown']):
                delay = max(delay, 60.0)
            if any(x in s for x in ['daily', 'per-day', '402', 'insufficient', 'credit']):
                delay = max(delay, 120.0)
            await asyncio.sleep(max(1.0, min(180.0, delay)))
    evidence['detail'] = last_detail
    (outdir / 'GENERATED.txt').write_text(content or '', encoding='utf-8')
    files = extract_files(content)
    for f in files:
        fp = outdir / f['path']
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f['content'], encoding='utf-8')
    evidence['files_extracted'] = len(files)
    evidence['files'] = [f['path'] for f in files]
    evidence['generated_chars'] = len(content or '')
    evidence['quality_notes'] = _quality_notes(files)
    if content and not files:
        evidence['warning'] = 'Model returned content but no `### FILE:` blocks were extracted. Inspect content_preview/GENERATED.txt.'
    (outdir / '_meta.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
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
    else:
        summary['temp_deleted'] = False
        summary['note_keep_temp'] = 'Temporary files kept under /tmp/kilo; delete when done.'
    return summary
