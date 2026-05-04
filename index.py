import json
import re
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler

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

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        if parsed.path == '/api/ping':
            self.wfile.write(json.dumps({'status': 'ok', 'version': '1.0'}).encode())
            return

        if parsed.path == '/api/sheet':
            url = params.get('url', [''])[0]
            sheet_name = params.get('sheet', [''])[0]
            if not url:
                self.wfile.write(json.dumps({'error': "Parametro url obrigatorio"}).encode())
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
                    self.wfile.write(json.dumps({'error': 'Planilha vazia'}).encode())
                    return
                headers = parse_csv_line(lines[0])
                rows = []
                for line in lines[1:]:
                    row = parse_csv_line(line)
                    while len(row) < len(headers):
                        row.append('')
                    rows.append(dict(zip(headers, row[:len(headers)])))
                result = json.dumps({'headers': headers, 'rows': rows, 'total': len(rows)}, ensure_ascii=False)
                self.wfile.write(result.encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        self.wfile.write(json.dumps({'error': 'Rota nao encontrada'}).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
