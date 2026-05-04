import json
import re
import urllib.request
import urllib.parse

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

def handler(request, response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Content-Type'] = 'application/json'

    path = request.path
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(request.url).query))

    if request.method == 'OPTIONS':
        response.status_code = 204
        return response

    if path == '/api/ping':
        response.status_code = 200
        response.body = json.dumps({'status': 'ok', 'version': '1.0'})
        return response

    if path == '/api/sheet':
        url = params.get('url', '')
        sheet_name = params.get('sheet', '')
        if not url:
            response.status_code = 400
            response.body = json.dumps({'error': 'Parametro url obrigatorio'})
            return response
        try:
            sheet_id = extract_sheet_id(url)
            gid = '&sheet=' + urllib.parse.quote(sheet_name) if sheet_name else ''
            csv_url = 'https://docs.google.com/spreadsheets/d/' + sheet_id + '/export?format=csv' + gid
            req = urllib.request.Request(csv_url, headers={'User-Agent': 'MetricDash/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('utf-8')
            lines = [l for l in raw.splitlines() if l.strip()]
            if not lines:
                response.status_code = 400
                response.body = json.dumps({'error': 'Planilha vazia'})
                return response
            headers = parse_csv_line(lines[0])
            rows = []
            for line in lines[1:]:
                row = parse_csv_line(line)
                while len(row) < len(headers):
                    row.append('')
                rows.append(dict(zip(headers, row[:len(headers)])))
            response.status_code = 200
            response.body = json.dumps({'headers': headers, 'rows': rows, 'total': len(rows)}, ensure_ascii=False)
            return response
        except Exception as e:
            response.status_code = 500
            response.body = json.dumps({'error': str(e)})
            return response

    response.status_code = 404
    response.body = json.dumps({'error': 'Rota nao encontrada'})
    return response
