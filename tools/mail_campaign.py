"""Prepare a newsletter, launch update or approved beta invitation. Preview is the default.

Run with the same environment as signup_service.py. --queue commits to the service outbox.
The preview operation rolls its transaction back and writes files only to --preview-dir.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import signup_service as service

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('file',type=Path,help='JSON: campaign_id, kind, subject/body OR email/access_url')
parser.add_argument('--queue',action='store_true',help='Commit messages to the live service outbox for delivery')
parser.add_argument('--preview-dir',type=Path,default=Path('email-preview'))
args=parser.parse_args()
data=json.loads(args.file.read_text(encoding='utf-8'))
if not isinstance(data.get('campaign_id'),str) or not data['campaign_id'].strip():
    parser.error('A stable, unique campaign_id is required.')
service.init_db()
with service.db() as conn:
    first=conn.execute('SELECT COALESCE(MAX(id),0) FROM outbox').fetchone()[0]
    if data['kind']=='beta_invite':
        count=int(service.queue_invitation(conn,data['email'].strip().lower(),data['access_url'],data['campaign_id']))
    else:
        count=service.queue_newsletter(conn,data['campaign_id'],data['subject'],data['body'],data['kind'])
    rows=conn.execute('SELECT * FROM outbox WHERE id>?',(first,)).fetchall()
    if not args.queue:
        conn.rollback()
        service.MAIL_TRANSPORT='preview'
        service.MAIL_PREVIEW_DIR=str(args.preview_dir)
        for row in rows:
            service.send_mail(row)
print(f'{count} messages '+('queued for delivery.' if args.queue else f'previewed locally in {args.preview_dir}; nothing queued or sent.'))
