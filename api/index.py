import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from flask import Flask, request, jsonify

app = Flask(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_MODELS = [
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "llama-3.3-70b-versatile"
]


def extract_sheet_id(url_or_id):
    match = re.search(r"spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id or "")
    return match.group(1) if match else (url_or_id or "").strip()


def parse_csv_line(line):
    result = []
    current = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                current.append('"')
                i += 1
            else:
                in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            result.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    result.append("".join(current).strip())
    return result


def request_json(url, payload, headers, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw), None, resp.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = str(e)
        return None, body, e.code
    except Exception as e:
        return None, str(e), 0


def list_models():
    url = f"{GROQ_BASE_URL}/models"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "MetricDash/1.0"
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return [m.get("id") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def call_ai(system, question):
    candidate_models = []
    env_model = os.environ.get("GROQ_MODEL", "").strip()
    if env_model:
        candidate_models.append(env_model)
    for m in DEFAULT_MODELS:
        if m not in candidate_models:
            candidate_models.append(m)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent": "MetricDash/1.0"
    }

    errors = []
    for model in candidate_models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question}
            ],
            "max_tokens": 1024,
            "temperature": 0.4
        }
        data, err, status = request_json(f"{GROQ_BASE_URL}/chat/completions", payload, headers, timeout=30)
        if data and data.get("choices"):
            return {
                "answer": data["choices"][0]["message"]["content"],
                "model": model,
                "attempts": errors
            }
        errors.append({"model": model, "status": status, "error": err})

    available = list_models() if GROQ_API_KEY else []
    raise RuntimeError(json.dumps({
        "message": "Nenhum modelo respondeu com sucesso",
        "attempted_models": candidate_models,
        "available_models": available,
        "errors": errors
    }, ensure_ascii=False))


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/ping", methods=["GET", "OPTIONS"])
@app.route("/ping", methods=["GET", "OPTIONS"])
def ping():
    if request.method == "OPTIONS":
        return ("", 204)
    return jsonify({"status": "ok", "version": "2.0"})


@app.route("/api/debug", methods=["GET", "OPTIONS"])
@app.route("/debug", methods=["GET", "OPTIONS"])
def debug():
    if request.method == "OPTIONS":
        return ("", 204)
    models = list_models() if GROQ_API_KEY else []
    return jsonify({
        "groq_key_set": bool(GROQ_API_KEY),
        "groq_key_length": len(GROQ_API_KEY),
        "groq_key_preview": (GROQ_API_KEY[:8] + "...") if GROQ_API_KEY else "VAZIA",
        "groq_base_url": GROQ_BASE_URL,
        "groq_model_env": os.environ.get("GROQ_MODEL", ""),
        "available_models": models[:20]
    })


@app.route("/api/sheet", methods=["GET", "OPTIONS"])
@app.route("/sheet", methods=["GET", "OPTIONS"])
def sheet():
    if request.method == "OPTIONS":
        return ("", 204)

    url_param = request.args.get("url", "")
    sheet_name = request.args.get("sheet", "")

    if not url_param:
        return jsonify({"error": "Parametro url obrigatorio"}), 400

    try:
        sheet_id = extract_sheet_id(url_param)
        gid = f"&gid={urllib.parse.quote(sheet_name)}" if sheet_name else ""
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid}"

        req = urllib.request.Request(csv_url, headers={"User-Agent": "MetricDash/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")

        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            return jsonify({"error": "Planilha vazia"}), 400

        headers = parse_csv_line(lines[0])
        rows = []
        for line in lines[1:]:
            row = parse_csv_line(line)
            while len(row) < len(headers):
                row.append("")
            rows.append(dict(zip(headers, row[:len(headers)])))

        return jsonify({"headers": headers, "rows": rows, "total": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ask", methods=["POST", "OPTIONS"])
@app.route("/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        body = request.get_json(force=True)
    except Exception as e:
        return jsonify({"error": f"Body invalido: {str(e)}"}), 400

    context = body.get("context", "")
    question = body.get("question", "")
    mode = body.get("mode", "generic-spreadsheet-analysis")

    if not question:
        return jsonify({"error": "Campo question obrigatorio"}), 400

    if not GROQ_API_KEY:
        return jsonify({"error": "Chave GROQ_API_KEY nao configurada"}), 500

    system = f"""
Voce e um assistente de analise de dados do MetricDash.
- Responda em portugues do Brasil.
- Use apenas os dados fornecidos.
- Nao invente metricas, datas, colunas ou comparacoes.
- Se faltar informacao, diga isso claramente.
- Se pedirem insights, entregue bullets curtos.
- Se houver ranking, cite nomes e valores.
MODO: {mode}
CONTEXTO DOS DADOS:
{context}
""".strip()

    user_prompt = f"Pergunta do usuario:\n{question}\n\nResponda com base apenas no contexto."

    try:
        result = call_ai(system, user_prompt)
        return jsonify({
            "answer": result["answer"],
            "model_used": result["model"],
            "attempts_before_success": result["attempts"]
        })
    except Exception as e:
        raw = str(e)
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"message": raw}
        return jsonify({
            "error": "Erro ao chamar IA",
            "details": parsed
        }), 500
