import json
import re
import os
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')

def extract_sheet_id(url_or_id):
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url_or_id)
    return m.group(1) if m else url_or_id.strip()

def parse_csv_line(line):
    result, current, in_quotes = [], [], False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            result.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    result.append(''.join(current).strip())
    return result

def call_ai(system, question):
    payload = json.dumps({
        "model": "openrouter/auto",
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': question}
        ],
        'max_tokens': 1024,
        'temperature': 0.4
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + OPENROUTER_API_KEY,
            'HTTP-Referer': 'https://metricdash.vercel.app',
            'X-Title': 'MetricDash'
        },
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data['choices'][0]['message']['content']

class handler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path in ('/api/ping', '/ping'):
            self.send_json({'status': 'ok', 'version': '1.0'})
            return

        if path in ('/api/debug', '/debug'):
            self.send_json({
                'openrouter_key_set': bool(OPENROUTER_API_KEY),
                'openrouter_key_length': len(OPENROUTER_API_KEY),
                'openrouter_key_preview': OPENROUTER_API_KEY[:8] + '...' if OPENROUTER_API_KEY else 'VAZIA'
            })
            return

        if path in ('/api/sheet', '/sheet'):
            url = params.get('url', [''])[0]
            sheet_name = params.get('sheet', [''])[0]
            if not url:
                self.send_json({'error': 'Parametro url obrigatorio'}, 400)
                return
            try:
                sheet_id = extract_sheet_id(url)
                gid = '&sheet=' + urllib.parse.quote(sheet_name) if sheet_name else ''
                csv_url = 'https://docs.google.com/spreadsheets/d/' + sheet_id + '/export?format=csv' + gid
                req = urllib.request.Request(csv_url, headers={'User-Agent': 'MetricDash/1.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode('utf-8')
                lines = [l for l in raw.splitlines() if l.strip()]
                if not lines:
                    self.send_json({'error': 'Planilha vazia'}, 400)
                    return
                headers = parse_csv_line(lines[0])
                rows = []
                for line in lines[1:]:
                    row = parse_csv_line(line)
                    while len(row) < len(headers):
                        row.append('')
                    rows.append(dict(zip(headers, row[:len(headers)])))
                self.send_json({'headers': headers, 'rows': rows, 'total': len(rows)})
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
            return

        self.send_json({'error': 'Rota nao encontrada'}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length else b'{}'
            body = json.loads(raw.decode('utf-8'))
        except Exception as e:
            self.send_json({'error': 'Body invalido: ' + str(e)}, 400)
            return

        if path in ('/api/ask', '/ask'):
            context = body.get('context', '')
            question = body.get('question', '')
            if not question:
                self.send_json({'error': 'Campo question obrigatorio'}, 400)
                return
            if not OPENROUTER_API_KEY:
                self.send_json({'error': 'Chave OPENROUTER_API_KEY nao configurada'}, 500)
                return
            system = (
                'Voce e um assistente de analise de dados do MetricDash. '
                'Responda sempre em portugues brasileiro, de forma clara e direta. '
                'Use os dados fornecidos para responder com precisao. '
                'Destaque insights, tendencias ou anomalias quando relevante. '
                'Seja conciso mas completo.\n\nDADOS:\n' + context
            )
            try:
                answer = call_ai(system, question)
                self.send_json({'answer': answer})
            except Exception as e:
                self.send_json({'error': 'Erro ao chamar IA: ' + str(e)}, 500)
            return

        self.send_json({'error': 'Rota nao encontrada'}, 404)
