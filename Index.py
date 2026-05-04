from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re

app = Flask(__name__)
CORS(app)

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

@app.route('/api/sheet')
def get_sheet():
    url = request.args.get('url', '')
    sheet_name = request.args.get('sheet', '')
    if not url:
        return jsonify({'error': "Parâmetro 'url' obrigatório"}), 400
    sheet_id = extract_sheet_id(url)
    gid = f'&sheet={requests.utils.quote(sheet_name)}' if sheet_name else ''
    csv_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid}'
    try:
        resp = requests.get(csv_url, timeout=10, headers={'User-Agent': 'MetricDash/1.0'})
        resp.raise_for_status()
        lines = [l for l in resp.text.splitlines() if l.strip()]
        if not lines:
            return jsonify({'error': 'Planilha vazia'}), 400
        headers = parse_csv_line(lines[0])
        rows = []
        for line in lines[1:]:
            row = parse_csv_line(line)
            while len(row) < len(headers):
                row.append('')
            rows.append(dict(zip(headers, row[:len(headers)])))
        return jsonify({'headers': headers, 'rows': rows, 'total': len(rows)})
    except Exception as e:
        return jsonifyy({'error': str(e)}), 500

@app.route('/api/ping')
def ping():
    return jsonify({'status': 'ok', 'version': '1.0'})

if __name__ == '__main__':
    app.run(debug=True)
