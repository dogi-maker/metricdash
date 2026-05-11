import json
import os
import re
import urllib.parse
import urllib.request


GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


def extract_sheet_id(url_or_id):
    match = re.search(r"spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id or "")
    return match.group(1) if match else (url_or_id or "").strip()


def parse_csv_line(line):
    result = []
    current = []
    in_quotes = False

    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            result.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    result.append("".join(current).strip())
    return result


def json_response(data, status=200):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(data, ensure_ascii=False),
    }


def call_ai(system, question):
    payload = json.dumps({
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question}
        ],
        "max_tokens": 1024,
        "temperature": 0.4
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data["choices"][0]["message"]["content"]


def handler(request):
    method = request.method
    url = urllib.parse.urlparse(request.path)
    path = url.path
    params = urllib.parse.parse_qs(url.query)

    if method == "OPTIONS":
        return json_response({}, 204)

    if method == "GET":
        if path in ["/api/ping", "/ping"]:
            return json_response({"status": "ok", "version": "1.1"})

        if path in ["/api/debug", "/debug"]:
            return json_response({
                "groq_key_set": bool(GROQ_API_KEY),
                "groq_key_length": len(GROQ_API_KEY),
                "groq_key_preview": (GROQ_API_KEY[:8] + "...") if GROQ_API_KEY else "VAZIA"
            })

        if path in ["/api/sheet", "/sheet"]:
            url_param = params.get("url", [""])[0]
            sheet_name = params.get("sheet", [""])[0]

            if not url_param:
                return json_response({"error": "Parametro url obrigatorio"}, 400)

            try:
                sheet_id = extract_sheet_id(url_param)
                gid = f"&gid={urllib.parse.quote(sheet_name)}" if sheet_name else ""
                csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid}"

                req = urllib.request.Request(
                    csv_url,
                    headers={"User-Agent": "MetricDash/1.0"}
                )

                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8")

                lines = [line for line in raw.splitlines() if line.strip()]
                if not lines:
                    return json_response({"error": "Planilha vazia"}, 400)

                headers = parse_csv_line(lines[0])
                rows = []

                for line in lines[1:]:
                    row = parse_csv_line(line)
                    while len(row) < len(headers):
                        row.append("")
                    rows.append(dict(zip(headers, row[:len(headers)])))

                return json_response({
                    "headers": headers,
                    "rows": rows,
                    "total": len(rows)
                })

            except Exception as e:
                return json_response({"error": str(e)}, 500)

        return json_response({"error": "Rota nao encontrada"}, 404)

    if method == "POST":
        if path in ["/api/ask", "/ask"]:
            try:
                body = request.get_json()
            except Exception as e:
                return json_response({"error": f"Body invalido: {str(e)}"}, 400)

            context = body.get("context", "")
            question = body.get("question", "")
            mode = body.get("mode", "generic-spreadsheet-analysis")

            if not question:
                return json_response({"error": "Campo question obrigatorio"}, 400)

            if not GROQ_API_KEY:
                return json_response({"error": "Chave GROQ_API_KEY nao configurada"}, 500)

            system = f"""
Voce e um assistente de analise de dados do MetricDash.

REGRAS DE RESPOSTA:
- Responda sempre em portugues do Brasil.
- Seja claro, direto e util.
- Use somente os dados fornecidos no contexto.
- Nao invente colunas, periodos, metas, meses ou comparacoes que nao existam.
- Se a planilha for simples, entregue insights simples e honestos.
- Se faltar informacao para responder exatamente, diga isso e ofereca a melhor leitura possivel com base no que existe.
- Quando fizer sentido, destaque:
  1. quem esta na frente,
  2. quem esta atras,
  3. quem esta acima ou abaixo da media,
  4. concentracao dos valores,
  5. anomalias ou distribuicao desigual.
- Se o usuario pedir insights, priorize resposta em bullets curtos.
- Se houver ranking, cite nomes e valores.
- Evite texto floreado.
- Nunca diga que analisou algo que nao aparece no contexto.

MODO:
{mode}

CONTEXTO DOS DADOS:
{context}
""".strip()

            user_prompt = f"""
Pergunta do usuario:
{question}

Responda com base apenas no contexto.
""".strip()

            try:
                answer = call_ai(system, user_prompt)
                return json_response({"answer": answer})
            except Exception as e:
                return json_response({"error": f"Erro ao chamar IA: {str(e)}"}, 500)

        return json_response({"error": "Rota nao encontrada"}, 404)

    return json_response({"error": "Metodo nao suportado"}, 405)
