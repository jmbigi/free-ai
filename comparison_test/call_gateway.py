import json, urllib.request, sys

API_KEY = "682499c35eaf5e9aa581bc4f60cadec5e4d9f780053e31dfda2e08adfa37e23d"
BASE = "http://127.0.0.1:8000"

with open("/home/kubuntu/free-ai/comparison_test/prompt.txt") as f:
    prompt = f.read()

def call_model(model_name):
    body = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 2000,
        "cache": False,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}/v1/chat/completions",
        data=data,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()[:500]}
    except Exception as e:
        return {"error": str(e)}
    return resp

def extract_code(resp):
    """Extrae el código Python de la respuesta."""
    if "error" in resp:
        return None, f"ERROR: {resp.get('error')}"
    choices = resp.get("choices", [])
    if not choices:
        return None, "No choices in response"
    content = choices[0].get("message", {}).get("content", "")
    if not content:
        return None, "Empty content"
    # Limpiar posible markdown
    content = content.strip()
    if content.startswith("```python"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    return content, None

def run_test(code_content):
    """Escribe el código en process.py y ejecuta los tests."""
    if code_content is None:
        return None, "No code to test"
    with open("/home/kubuntu/free-ai/comparison_test/process.py", "w") as f:
        f.write(code_content)
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "unittest", "test_process.py", "-v"],
        cwd="/home/kubuntu/free-ai/comparison_test",
        capture_output=True, text=True, timeout=30
    )
    return result.stdout + result.stderr, result.returncode

def main():
    for model_name in ["local-ollama/qwen3-coder-opt:latest", "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"]:
        print(f"\n{'='*60}")
        print(f"MODEL: {model_name}")
        print(f"{'='*60}")
        resp = call_model(model_name)
        if "error" in resp:
            print(f"  ERROR: {resp['error']}")
            if "body" in resp:
                print(f"  Body: {resp['body']}")
            continue
        
        # Mostrar respuesta cruda resumida
        choices = resp.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            print(f"  Finish reason: {choices[0].get('finish_reason')}")
            print(f"  Content length: {len(content)} chars")
            print(f"  Content preview: {content[:200]}...")
        else:
            print(f"  Full response: {resp}")
            continue
        
        code, err = extract_code(resp)
        if err:
            print(f"  Extraction error: {err}")
            print(f"  Raw content: {content[:500]}")
            continue
        
        print(f"  Extracted code length: {len(code)} chars")
        print(f"  Code preview: {code[:200]}...")
        
        # Ejecutar tests
        output, returncode = run_test(code)
        print(f"  Test return code: {returncode}")
        print(f"  Test output:")
        for line in output.split("\n")[:30]:
            print(f"    {line}")
        if len(output.split("\n")) > 30:
            print(f"    ... ({len(output.split(chr(10)))-30} more lines)")

if __name__ == "__main__":
    main()
