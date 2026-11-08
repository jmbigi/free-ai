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
MAX_FILES = 60
MAX_FILE_BYTES = 250_000


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


_NON_INT_ARG_RE = re.compile(r'\b(token|uuid|idempotency[_a-z]*|request_id|trace_id|saga_id|corr(?:elation)?_id|step[_a-z]*id|message_id|key)\b', re.I)
_FMT_SPEC_RE = re.compile(r'%(?:\([^)]+\))?[-+#0 ]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa%]')
_LOGGER_CALL_RE = re.compile(r'logger\.(debug|info|warning|error|exception|critical)\s*\(([^)]{0,400})\)')

def _autofix_logging_formats(text: str) -> tuple[str, list[dict[str, Any]]]:
    fixes = []
    def repl(m: re.Match) -> str:
        level, inner = m.group(1), m.group(2)
        # split format string (first arg) from rest - simple heuristic
        if not inner.lstrip().startswith(("'", '"', "f'", 'f"', "r'", 'r"')):
            return m.group(0)
        # find end of first string literal crudely
        q = inner.lstrip()[0]
        if inner.lstrip().startswith(('f', 'r')): q = inner.lstrip()[1]
        i = inner.find(q)
        if i < 0: return m.group(0)
        j = i + 1
        while j < len(inner):
            if inner[j] == '\\': j += 2; continue
            if inner[j] == q: break
            j += 1
        if j >= len(inner): return m.group(0)
        fmt = inner[i:j+1]
        rest = inner[j+1:]
        specs = list(_FMT_SPEC_RE.finditer(fmt))
        if not specs or '%d' not in fmt and '%i' not in fmt: return m.group(0)
        args = [a.strip() for a in rest.split(',') if a.strip()]
        new_fmt = fmt
        changed = False
        for si, sp in enumerate(specs):
            if sp.group(0) not in ('%d','%i'): continue
            if si >= len(args): continue
            if _NON_INT_ARG_RE.search(args[si]):
                # replace this occurrence index
                occ = [x for x in _FMT_SPEC_RE.finditer(new_fmt)]
                if si < len(occ) and occ[si].group(0) in ('%d','%i'):
                    s,e = occ[si].span(); new_fmt = new_fmt[:s] + '%s' + new_fmt[e:]; changed = True
        if changed:
            fixes.append({'check':'logging_format_autofix','from':fmt[:120],'to':new_fmt[:120],'args_sample':args[:6]})
            return f"logger.{level}({new_fmt}{rest})"
        return m.group(0)
    return _LOGGER_CALL_RE.sub(repl, text), fixes

def _quality_notes(files: list[dict[str, str]]) -> list[dict[str, Any]]:
    notes = []
    for f in files:
        path = f['path']
        content = f['content']
        if path.endswith('.py'):
            fixed, fixes = _autofix_logging_formats(content)
            if fixes and fixed != content:
                content = fixed
                f['content'] = content
                for fx in fixes:
                    notes.append({'path': path, **fx, 'ok': True})
            try:
                ast.parse(content)
                notes.append({'path': path, 'check': 'python_ast', 'ok': True})
            except Exception as e:
                notes.append({'path': path, 'check': 'python_ast', 'ok': False, 'error': str(e)[:220]})
            for m in re.finditer(r'logger\.(?:debug|info|warning|error|exception|critical)\s*\(([^)]{0,500})\)', content):
                call = m.group(1)
                if not call.lstrip().startswith(("'", '"', "f'", 'f"', "r'", 'r"')): continue
                # find format literal and args
                q = call.lstrip()[0]
                if call.lstrip().startswith(('f','r')): q = call.lstrip()[1]
                i = call.find(q)
                if i < 0: continue
                j = i+1
                while j < len(call):
                    if call[j]=='\\': j+=2; continue
                    if call[j]==q: break
                    j+=1
                if j>=len(call): continue
                fmt = call[i:j+1]; rest = call[j+1:]
                specs = [s.group(0) for s in _FMT_SPEC_RE.finditer(fmt)]
                args = [a.strip() for a in rest.split(',') if a.strip()]
                bad = False
                for si,sp in enumerate(specs):
                    if sp in ('%d','%i') and si < len(args) and _NON_INT_ARG_RE.search(args[si]):
                        bad = True; break
                if bad:
                    notes.append({'path': path, 'check': 'logging_format_heuristic', 'ok': False,
                                  'warning': 'Int format (%d/%i) used for likely non-int arg (token/uuid/id).', 'sample': call[:180]})
                    break
        elif path.endswith('.json'):
            try:
                json.loads(content)
                notes.append({'path': path, 'check': 'json', 'ok': True})
            except Exception as e:
                notes.append({'path': path, 'check': 'json', 'ok': False, 'error': str(e)[:220]})
        # write possibly fixed content to output dir will use f['content']
    return notes


async def generate_one(*, prompt: str, name: str, model: str = 'auto', max_tokens: int = 3200,
                       temperature: float = 0, max_retries: int = 3, retry_delay_s: float = 20.0,
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
    }
    base_system = (
        'You are a senior software engineer. Output ONLY project files, no preamble, no thinking, no analysis. '
        'For EVERY file use exactly:\n### FILE: relative/path.ext\n```lang\n<content>\n```\n'
        'Rules: no absolute paths; no ".."; Python must be syntactically valid; include README and tests when useful. '
        'Code quality: use `%s` for UUID/str/token/id/request_id/trace_id/saga_id (never `%d`/`%i` for them); '
        '`%d`/`%i` only for real ints (attempt counters, counts). Handle errors explicitly. Deterministic retries/idempotency in simulations. Minimal coherent implementation.'
    )
    strict_retry = (
        prompt.rstrip() + '\n\nIMPORTANT: Return ONLY `### FILE: ...` blocks with complete code. No explanation. '
        'Fix logging placeholders: token/uuid/id/request_id -> `%s`; integer attempt/count -> `%d`.'
    )
    payload = {
        'model': model, 'temperature': temperature, 'max_tokens': max(256, min(8192, max_tokens)),
        'messages': [{'role': 'system', 'content': base_system}, {'role': 'user', 'content': prompt}],
        'stream': False, 'gateway': {'max_retries': int(getattr(settings, 'default_max_retries', 4) or 4)},
    }
    content = ''
    last_detail = None
    for attempt in range(1, max(1, min(5, max_retries)) + 1):
        try:
            if attempt > 1 and (not extract_files(content)):
                payload['messages'][1]['content'] = strict_retry
                payload['max_tokens'] = max(payload.get('max_tokens') or 1800, 1200)
            data, attempts = await execute_with_fallback(dict(payload))
            g = data.get('gateway') or {}
            msg = ((data.get('choices') or [{}])[0].get('message') or {})
            content = msg.get('content') or ''
            if not content and not msg.get('tool_calls'): content = msg.get('reasoning') or msg.get('reasoning_content') or ''
            files_now = extract_files(content)
            ok = bool(content and files_now and not data.get('detail') and not data.get('error'))
            meta = {'attempt': attempt, 'ok': ok, 'selected': g.get('selected') or data.get('model'),
                    'gateway_attempts': len(attempts or g.get('attempts') or []), 'fallback_used': g.get('fallback_used'),
                    'files_detected': len(files_now)}
            evidence['attempts_meta'].append(meta)
            evidence['selected'] = meta['selected']
            evidence['last_gateway'] = g
            if ok:
                evidence['ok'] = True
                break
            last_detail = data.get('detail') or data.get('error') or ('no ### FILE blocks extracted' if content else 'empty content')
        except Exception as e:
            last_detail = {'message': str(e)[:500], 'attempts': getattr(e, 'attempts', None)}
            evidence['attempts_meta'].append({'attempt': attempt, 'ok': False, 'error': str(e)[:300]})
        if attempt < max_retries:
            delay = retry_delay_s
            s = json.dumps(last_detail, ensure_ascii=False).lower() if last_detail else ''
            if any(x in s for x in ['429', 'rate limit', 'free limit', 'every 45', 'cooldown']):
                delay = max(delay, 45.0)
            if any(x in s for x in ['daily', 'per-day', '402', 'insufficient', 'credit']):
                delay = max(delay, 90.0)
            await asyncio.sleep(max(0.5, min(180.0, delay)))
    evidence['detail'] = last_detail
    (outdir / 'GENERATED.txt').write_text(content or '', encoding='utf-8')
    files = extract_files(content)
    quality_notes = _quality_notes(files)
    for f in files:
        fp = outdir / f['path']
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f['content'], encoding='utf-8')
    evidence['files_extracted'] = len(files)
    evidence['files'] = [f['path'] for f in files]
    evidence['generated_chars'] = len(content or '')
    evidence['quality_notes'] = quality_notes
    if content and not files:
        evidence['warning'] = 'No `### FILE:` blocks extracted after retries. content_preview contains raw model output.'
    (outdir / '_meta.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {k: v for k, v in evidence.items() if k not in ('last_gateway',)}
    summary['output_dir'] = str(outdir)
    summary['files'] = evidence['files']
    summary['content_preview'] = (content or '')[:6000]
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
