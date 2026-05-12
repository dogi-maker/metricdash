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
    text = (url_or_id or "").strip()
    match = re.search(r"spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if match:
        return match.group(1)
    return text


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
            "temperature": 0.2
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
    return jsonify({"status": "ok", "version": "2.1"})


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
    sheet_name = request.args.get("sheet", "").strip()

    if not url_param:
        return jsonify({"error": "Parametro url obrigatorio"}), 400

    try:
        sheet_id = extract_sheet_id(url_param)
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        if sheet_name:
            export_url += f"&sheet={urllib.parse.quote(sheet_name)}"

        req = urllib.request.Request(export_url, headers={"User-Agent": "MetricDash/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")

        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            return jsonify({"error": "Planilha vazia ou aba nao encontrada"}), 400

        headers = parse_csv_line(lines[0])
        rows = []
        for line in lines[1:]:
            row = parse_csv_line(line)
            while len(row) < len(headers):
                row.append("")
            rows.append(dict(zip(headers, row[:len(headers)])))

        return jsonify({"headers": headers, "rows": rows, "total": len(rows), "sheet_id": sheet_id})
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        return jsonify({"error": f"Google Sheets respondeu HTTP {e.code}", "details": detail}), 500
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
Você é um assistente de análise de dados do MetricDash.

REGRAS:
- Responda sempre em português do Brasil.
- Use apenas os dados fornecidos no contexto.
- Não invente categorias, nomes de entidades, meses, colunas, áreas de negócio ou tipos de registro.
- Nunca assuma que os itens são 'comidas', 'produtos', 'clientes', 'vendas' ou qualquer outro tipo fixo, a menos que isso esteja explicitamente nas colunas ou no contexto.
- Sempre use os nomes reais das colunas ao explicar os resultados.
- Se houver uma análise cruzada entre uma coluna categórica e uma coluna numérica, diga explicitamente algo como: 'Na coluna X, o item Y tem o maior valor em Z'.
- Evite substantivos genéricos errados. Prefira 'item', 'registro', 'linha', 'categoria', ou o nome da coluna.
- Se a estrutura da planilha for ambígua, diga isso com honestidade.
- Se pedirem insights, entregue bullets curtos.
- Se houver ranking, cite nomes e valores.
- Não diga nada que não esteja apoiado no contexto.

MODO: {mode}

CONTEXTO DOS DADOS:
{context}
""".strip()

    user_prompt = f"Pergunta do usuario:\n{question}\n\nResponda com base apenas no contexto e use os nomes das colunas da planilha quando fizer referência aos dados."

    try:
        result = call_ai(system, user_prompt)
        return jsonify({
            "answer": result["answer"],
            "model_used": result["model"],
            "attempts_before_success": result["attempts"]
        })
    except Exception as e:
        raw = str(e)
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"message": raw}
        return jsonify({"error": "Erro ao chamar IA", "details": parsed}), 500
