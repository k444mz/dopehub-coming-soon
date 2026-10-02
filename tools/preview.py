"""Local-only preview: isolated SQLite database and email files; never sends mail."""
import os
import sys
import json
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'preview/local'
DATA.mkdir(parents=True, exist_ok=True)
os.environ.update(SIGNUP_DB=str(DATA / 'signups.db'), MAIL_TRANSPORT='preview',
    MAIL_PREVIEW_DIR=str(DATA / 'emails'), PUBLIC_URL='http://127.0.0.1:8775',
    SIGNUP_ORIGINS='http://127.0.0.1:8775,http://localhost:8775', ADMIN_SECRET='',
    MAIL_FROM='no-reply@dopehub.net', REPLY_TO='contact@dopehub.net', ALERT_TO='contact@dopehub.net',
    RELAY_TOKEN='', SMTP_PASS='', BETA_INVITE_ORIGIN='')
sys.path.insert(0,str(ROOT / 'server'))
import signup_service as service

class Preview(service.Handler, SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'site'),**kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/') or path.startswith('/admin/api/'):
            return service.Handler.do_GET(self)
        if path == '/__mail/':
            folder = DATA/'emails'
            entries = []
            for file in sorted(folder.glob('*.json'),key=lambda f:f.stat().st_mtime,reverse=True):
                data = json.loads(file.read_text(encoding='utf-8'))
                entries.append(f'<article><h2><a href="{file.stem}.html">{service.esc(data["subject"])}</a></h2><p>From: {service.esc(data["fromName"])} &lt;{service.esc(data["from"])}&gt;<br>To: {service.esc(data["to"])}<br>Reply-To: {service.esc(data["replyTo"])}</p><pre>{service.esc(data["text"])}</pre></article>')
            html = '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width"><title>DopeHub local email preview</title><style>body{font:16px/1.6 system-ui;max-width:850px;margin:40px auto;padding:20px;background:#f6f5ee;color:#183d32}article{padding:20px;background:white;margin:20px 0;border:1px solid #ccd9c5}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#285f45}</style><h1>Local email preview</h1><p>No messages leave this computer. All data here is local test data.</p><a href="/">Back to the website</a>'+(''.join(entries) or '<p>Submit a local form to see its email here.</p>')+'</html>'
            return self.reply(200,ctype='text/html; charset=utf-8',body=html.encode())
        if path.startswith('/__mail/'):
            name=path.removeprefix('/__mail/')
            if '/' not in name and '\\' not in name and name.endswith('.html'):
                file=DATA/'emails'/name
                if file.is_file():
                    return self.reply(200,ctype='text/html; charset=utf-8',body=file.read_bytes())
            return self.reply(404,{'error':'Not found'})
        return SimpleHTTPRequestHandler.do_GET(self)

    def end_headers(self):
        if not urlsplit(self.path).path.startswith('/__mail/'):
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
        self.send_header('Cache-Control','no-store')
        super().end_headers()

if __name__=='__main__':
    service.init_db()
    threading.Thread(target=service.mailer,daemon=True).start()
    print('Website: http://127.0.0.1:8775/ | Local email: http://127.0.0.1:8775/__mail/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8775),Preview).serve_forever()
