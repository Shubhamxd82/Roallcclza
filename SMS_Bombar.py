#!/usr/bin/env python3
"""
SMS_Bombar_open_no_admin_token.py  (open lab — admin-token removed)

Local SMS/CALL simulation lab (educational). This single-file tool includes:
 - Mock HTTP API to POST /send_sms
 - Simple web UI for manual sends and viewing messages
 - CLI utilities: init-db, run-server, send (CLI client), export-csv
 - Per-client and per-target in-memory rate limiting
 - Simulated delivery delay option
 - Structured file + console logging
 - Protected-numbers table + open (no-token) protect/unprotect management

SAFETY NOTES (read before use):
 - Use only in isolated VM / host-only networks. Never target real carriers or real phone numbers.
 - Consent required in each send payload (the server enforces `consent=true`).
 - This tool is for educational testing only. Misuse may be illegal.
"""

from flask import Flask, request, jsonify, render_template_string, redirect, url_for, send_file
import argparse
import sqlite3
import time
import threading
import csv
import random
from collections import deque, defaultdict
from concurrent.futures import ThreadPoolExecutor
import sys
import os
import io
import logging

# ------------------------------
# Logging setup
# ------------------------------
LOG_FILE = os.environ.get('SMS_LAB_LOG', 'sms_lab.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("sms_lab")

# ------------------------------
# DB schema (whitelist removed — lab is open)
# Add protected_numbers table for numbers that must NOT be targeted
# ------------------------------
DB_SCHEMA = '''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_number TEXT,
    body TEXT,
    timestamp REAL,
    status TEXT
);

CREATE TABLE IF NOT EXISTS protected_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_number TEXT UNIQUE,
    added_ts REAL
);
'''

# ------------------------------
# Simple in-memory rate limiter
# ------------------------------
class SimpleRateLimiter:
    def __init__(self, max_per_minute=300):
        self.max_per_minute = max_per_minute
        self.data = defaultdict(lambda: deque())
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        window_start = now - 60.0
        with self.lock:
            q = self.data[key]
            while q and q[0] < window_start:
                q.popleft()
            if len(q) >= self.max_per_minute:
                return False
            q.append(now)
            return True

RATE_LIMITER = SimpleRateLimiter(max_per_minute=300)
PER_TARGET_LIMITER = SimpleRateLimiter(max_per_minute=60)

# ------------------------------
# DB helpers & protected-number helpers
# ------------------------------

def get_conn(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return conn

def init_db(db_path):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.executescript(DB_SCHEMA)
    conn.commit()
    conn.close()
    logger.info("Initialized DB at %s (messages + protected_numbers tables created). Lab is open — any destination allowed.", db_path)

def export_csv(db_path, out_path):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, to_number, body, timestamp, status FROM messages ORDER BY timestamp DESC")
    rows = cur.fetchall()
    conn.close()
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['id','to','body','timestamp','status'])
        for r in rows:
            w.writerow(r)
    logger.info("Exported %d messages to %s", len(rows), out_path)

# Protected numbers helpers
def add_protected_number(db_path, to_number):
    conn = get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO protected_numbers (to_number, added_ts) VALUES (?,?)", (str(to_number), time.time()))
        conn.commit()
        changed = cur.rowcount > 0
    finally:
        conn.close()
    return changed

def remove_protected_number(db_path, to_number):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM protected_numbers WHERE to_number = ?", (str(to_number),))
    removed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return removed

def list_protected_numbers(db_path):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT to_number, added_ts FROM protected_numbers ORDER BY added_ts DESC")
    rows = cur.fetchall()
    conn.close()
    return [{"to": r[0], "added_ts": r[1]} for r in rows]

def is_protected(db_path, to_number):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM protected_numbers WHERE to_number = ? LIMIT 1", (str(to_number),))
    row = cur.fetchone()
    conn.close()
    return row is not None

# ------------------------------
# Flask app (API + simplified UI)
# ------------------------------

def create_app(db_path, bind_host="127.0.0.1", per_target_rate=60, simulate_delay=0):
    app = Flask(__name__)

    PER_TARGET_LIMITER.max_per_minute = per_target_rate
    app.config['SIMULATE_DELAY'] = float(simulate_delay)
    app.config['DB_PATH'] = db_path

    INDEX_HTML = '''
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <title>SMS_Bombar — Open Lab UI</title>
        <style>
          body{font-family: Arial, Helvetica, sans-serif; margin:20px}
          .card{border:1px solid #ddd;padding:12px;margin-bottom:12px;border-radius:6px}
          label{display:block;margin-top:6px}
          input[type=text], textarea{width:100%;padding:8px}
          button{padding:8px 12px;margin-top:8px}
          table{width:100%;border-collapse:collapse}
          th,td{padding:8px;border:1px solid #eee}
        </style>
      </head>
      <body>
        <h2>SMS_Bombar — Open Local SMS Lab (UI)</h2>
        <p><strong>Safety:</strong> Use only on isolated networks. Consent required.</p>

        <div class="card">
          <h3>Send Message (Lab is OPEN — any destination accepted)</h3>
          <form method="post" action="/ui/send">
            <label>To (destination number)</label>
            <input name="to" placeholder="e.g. 1001" required>
            <label>Body</label>
            <textarea name="body">Lab test message</textarea>
            <label><input type="checkbox" name="consent" value="1" required> I confirm consent for this destination</label>
            <button type="submit">Send</button>
          </form>
        </div>

        <div class="card">
          <h3>Protected Numbers (these will NOT be targeted)</h3>
          <p>Protected numbers can be managed via CLI or via open /protect endpoints.</p>
          <form method="post" action="/ui/protect-add" style="margin-bottom:8px">
            <label>Add protected number</label>
            <input name="to" placeholder="e.g. 1001" required>
            <button type="submit">Add</button>
          </form>
          <form method="post" action="/ui/protect-remove">
            <label>Remove protected number</label>
            <input name="to" placeholder="e.g. 1001" required>
            <button type="submit">Remove</button>
          </form>
          <h4>List</h4>
          <table>
            <thead><tr><th>To</th><th>Added</th></tr></thead>
            <tbody>
            {% for p in protected %}
              <tr>
                <td>{{ p.to }}</td>
                <td>{{ p.added_readable }}</td>
              </tr>
            {% endfor %}
            </tbody>
          </table>
        </div>

        <div class="card">
          <h3>Recent Messages</h3>
          <p><a href="/messages">View JSON /messages</a> | <a href="/export-csv">Export CSV</a></p>
          <table>
            <thead><tr><th>ID</th><th>To</th><th>Body</th><th>Time</th><th>Status</th></tr></thead>
            <tbody>
            {% for m in messages %}
              <tr>
                <td>{{ m.id }}</td>
                <td>{{ m.to }}</td>
                <td>{{ m.body }}</td>
                <td>{{ m.ts_readable }}</td>
                <td>{{ m.status }}</td>
              </tr>
            {% endfor %}
            </tbody>
          </table>
        </div>

      </body>
    </html>
    '''

    @app.route('/')
    def index():
        conn = get_conn(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, to_number, body, timestamp, status FROM messages ORDER BY timestamp DESC LIMIT 100")
        rows = cur.fetchall()
        cur.execute("SELECT to_number, added_ts FROM protected_numbers ORDER BY added_ts DESC")
        prot_rows = cur.fetchall()
        conn.close()
        messages = []
        for r in rows:
            messages.append({
                'id': r[0], 'to': r[1], 'body': r[2], 'ts': r[3], 'status': r[4],
                'ts_readable': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r[3]))
            })
        protected = []
        for p in prot_rows:
            protected.append({'to': p[0], 'added_ts': p[1], 'added_readable': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p[1]))})
        return render_template_string(INDEX_HTML, messages=messages, protected=protected)

    @app.route('/ui/send', methods=['POST'])
    def ui_send():
        payload = {
            'to': request.form.get('to', '').strip(),
            'body': request.form.get('body', '').strip(),
            'consent': bool(request.form.get('consent'))
        }
        resp = app.test_client().post('/send_sms', json=payload)
        logger.info('UI send -> status %s payload=%s resp=%s', resp.status_code, payload, resp.get_data(as_text=True))
        return redirect(url_for('index'))

    @app.route('/ui/protect-add', methods=['POST'])
    def ui_protect_add():
        to = request.form.get('to', '').strip()
        if not to:
            return redirect(url_for('index'))
        added = add_protected_number(db_path, to)
        logger.info("UI added protected number %s (added=%s)", to, added)
        return redirect(url_for('index'))

    @app.route('/ui/protect-remove', methods=['POST'])
    def ui_protect_remove():
        to = request.form.get('to', '').strip()
        if not to:
            return redirect(url_for('index'))
        removed = remove_protected_number(db_path, to)
        logger.info("UI removed protected number %s (removed=%s)", to, removed)
        return redirect(url_for('index'))

    @app.route('/send_sms', methods=['POST'])
    def send_sms():
        remote = request.remote_addr or 'unknown'
        if not RATE_LIMITER.allow(remote):
            logger.warning('Rate limit exceeded for %s', remote)
            return jsonify({"ok": False, "error": "rate_limit_exceeded"}), 429

        payload = request.get_json(force=True, silent=True) or {}
        to_number = str(payload.get('to', '')).strip()
        body = str(payload.get('body', '')).strip()
        consent = bool(payload.get('consent', False))

        if not to_number:
            return jsonify({"ok": False, "error": "missing_to"}), 400
        if not consent:
            return jsonify({"ok": False, "error": "consent_required"}), 400

        # Check protected numbers: these must not be targeted
        if is_protected(db_path, to_number):
            logger.warning('Attempt to send to protected number %s', to_number)
            return jsonify({"ok": False, "error": "protected_number"}), 403

        if not PER_TARGET_LIMITER.allow(to_number):
            logger.warning('Per-target rate exceeded for %s', to_number)
            return jsonify({"ok": False, "error": "per_target_rate_limit_exceeded"}), 429

        ts = time.time()
        conn = get_conn(db_path)
        cur = conn.cursor()
        cur.execute("INSERT INTO messages (to_number, body, timestamp, status) VALUES (?,?,?,?)",
                    (to_number, body, ts, 'queued'))
        mid = cur.lastrowid
        conn.commit()

        delay = 0.0
        try:
            sd = float(app.config.get('SIMULATE_DELAY', 0))
            if sd > 0:
                delay = random.uniform(0, sd)
        except Exception:
            delay = 0.0

        if delay > 0:
            def deliver_later(db_path_local, message_id, dly):
                time.sleep(dly)
                conn2 = get_conn(db_path_local)
                cur2 = conn2.cursor()
                cur2.execute("UPDATE messages SET status=? WHERE id=?", ('delivered', message_id))
                conn2.commit()
                conn2.close()
                logger.info('Delivered message id=%s after %fs', message_id, dly)

            t = threading.Thread(target=deliver_later, args=(db_path, mid, delay), daemon=True)
            t.start()
            status = 'queued'
            logger.info('Message queued id=%s to=%s delay=%s', mid, to_number, delay)
        else:
            cur.execute("UPDATE messages SET status=? WHERE id=??", ('delivered', mid))
            conn.commit()
            status = 'delivered'
            logger.info('Message delivered id=%s to=%s', mid, to_number)

        conn.close()
        return jsonify({"ok": True, "message_id": mid, "status": status, "simulate_delay": delay}), 200

    @app.route('/messages', methods=['GET'])
    def list_messages():
        conn = get_conn(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, to_number, body, timestamp, status FROM messages ORDER BY timestamp DESC")
        rows = cur.fetchall()
        conn.close()
        data = [{"id": r[0], "to": r[1], "body": r[2], "ts": r[3], "status": r[4]} for r in rows]
        return jsonify(data)

    @app.route('/export-csv', methods=['GET'])
    def export_csv_ui():
        conn = get_conn(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, to_number, body, timestamp, status FROM messages ORDER BY timestamp DESC")
        rows = cur.fetchall()
        conn.close()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['id','to','body','timestamp','status'])
        for r in rows:
            w.writerow(r)
        buf.seek(0)
        return send_file(io.BytesIO(buf.getvalue().encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name='messages_export.csv')

    # Open protect/unprotect endpoints (NO admin token required)
    @app.route('/protect/add', methods=['POST'])
    def protect_add():
        payload = request.get_json(force=True, silent=True) or {}
        to = str(payload.get('to', '')).strip()
        if not to:
            return jsonify({"ok": False, "error": "missing_to"}), 400
        added = add_protected_number(db_path, to)
        logger.info('Protected number added: %s (added=%s)', to, added)
        return jsonify({"ok": True, "added": added, "to": to}), 200

    @app.route('/protect/remove', methods=['POST'])
    def protect_remove():
        payload = request.get_json(force=True, silent=True) or {}
        to = str(payload.get('to', '')).strip()
        if not to:
            return jsonify({"ok": False, "error": "missing_to"}), 400
        removed = remove_protected_number(db_path, to)
        logger.info('Protected number removed: %s (removed=%s)', to, removed)
        return jsonify({"ok": True, "removed": removed, "to": to}), 200

    @app.route('/protect/list', methods=['GET'])
    def protect_list():
        prot = list_protected_numbers(db_path)
        return jsonify({"ok": True, "protected": prot}), 200

    return app

# ------------------------------
# CLI sender (client)
# ------------------------------
try:
    import requests
except Exception:
    requests = None

def sender_main(db_path, target, body, rate, count, concurrency, api_url=None):
    if requests is None:
        raise RuntimeError("requests not installed. Run: pip install requests")

    api_url = api_url or os.environ.get('SMS_LAB_API', 'http://127.0.0.1:5000/send_sms')
    delay = 1.0 / rate if rate > 0 else 0

    def send_one(i):
        payload = {"to": str(target), "body": f"{body} [{i}]", "consent": True}
        try:
            r = requests.post(api_url, json=payload, timeout=10)
            try:
                resp = r.json()
            except Exception:
                resp = r.text
            logger.info('[%s] attempt %s -> %s %s', target, i, r.status_code, resp)
        except Exception as e:
            logger.exception('Error sending attempt %s to %s: %s', i, target, e)

    msgs_per_worker = count // concurrency
    extra = count % concurrency

    def worker(start_index, n_msgs):
        for j in range(n_msgs):
            idx = start_index + j + 1
            send_one(idx)
            if delay > 0:
                time.sleep(delay)

    tasks = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        start = 0
        for i in range(concurrency):
            n = msgs_per_worker + (1 if i < extra else 0)
            if n <= 0:
                continue
            tasks.append(ex.submit(worker, start, n))
            start += n
        for t in tasks:
            t.result()

# ------------------------------
# CLI & arg parsing (whitelist commands removed)
# Add protect CLI commands
# ------------------------------

def build_parser():
    p = argparse.ArgumentParser(description='SMS_Bombar — Open Local SMS lab single-file tool (updated: admin-token removed)')
    p.add_argument('--db', default='./sms_lab.db', help='sqlite db path (default: ./sms_lab.db)')

    sub = p.add_subparsers(dest='cmd')

    sub_init = sub.add_parser('init-db', help='create DB (messages table)')

    sub_run = sub.add_parser('run-server', help='run the mock SMS HTTP server (with UI)')
    sub_run.add_argument('--host', default='127.0.0.1', help='host to bind (default 127.0.0.1)')
    sub_run.add_argument('--port', type=int, default=5000, help='port to bind (default 5000)')
    sub_run.add_argument('--rate-limit', type=int, default=300, help='max requests per minute per client IP')
    sub_run.add_argument('--per-target-rate', type=int, default=60, help='max messages per minute per target number')
    sub_run.add_argument('--simulate-delay', type=float, default=0.0, help='max random delivery delay in seconds (0 disables)')

    sub_send = sub.add_parser('send', help='client sender to post messages to local server')
    sub_send.add_argument('--to', required=True, help='destination (lab accepts any destination)')
    sub_send.add_argument('--body', default='Lab test message', help='message body')
    sub_send.add_argument('--rate', type=float, default=1.0, help='messages per second (e.g., 1.0 => 1 msg/s)')
    sub_send.add_argument('--count', type=int, default=10, help='total messages to send')
    sub_send.add_argument('--concurrency', type=int, default=1, help='parallel workers')
    sub_send.add_argument('--api-url', default=None, help='override API URL (default http://127.0.0.1:5000/send_sms)')

    sub_export = sub.add_parser('export-csv', help='export messages table to CSV')
    sub_export.add_argument('outpath', help='output CSV file path')

    # Protect management (CLI)
    sub_protect_add = sub.add_parser('protect-add', help='add a protected number (will NOT be targeted)')
    sub_protect_add.add_argument('--to', required=True, help='number to protect')

    sub_protect_remove = sub.add_parser('protect-remove', help='remove a protected number')
    sub_protect_remove.add_argument('--to', required=True, help='number to remove from protected list')

    sub_protect_list = sub.add_parser('protect-list', help='list protected numbers')

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = args.db

    if args.cmd is None:
        parser.print_help()
        return

    if args.cmd == 'init-db':
        init_db(db_path)
        return

    if args.cmd == 'run-server':
        try:
            app = create_app(db_path, bind_host=args.host, per_target_rate=args.per_target_rate, simulate_delay=args.simulate_delay)
        except Exception as e:
            logger.exception('Failed to create app: %s', e)
            print('Missing dependency (Flask). Run: pip install flask')
            return
        RATE_LIMITER.max_per_minute = args.rate_limit
        logger.info('Starting server on %s:%s DB=%s', args.host, args.port, db_path)
        app.run(host=args.host, port=args.port)
        return

    if args.cmd == 'send':
        sender_main(db_path, args.to, args.body, args.rate, args.count, args.concurrency, api_url=args.api_url)
        return

    if args.cmd == 'export-csv':
        export_csv(db_path, args.outpath)
        return

    if args.cmd == 'protect-add':
        init_db(db_path)  # ensure tables exist
        added = add_protected_number(db_path, args.to)
        print(f"Protected number {args.to} added: {added}")
        return

    if args.cmd == 'protect-remove':
        init_db(db_path)
        removed = remove_protected_number(db_path, args.to)
        print(f"Protected number {args.to} removed: {removed}")
        return

    if args.cmd == 'protect-list':
        init_db(db_path)
        prot = list_protected_numbers(db_path)
        if not prot:
            print("No protected numbers.")
            return
        for p in prot:
            print(f"{p['to']} (added: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p['added_ts']))})")
        return

if __name__ == '__main__':
    main()
