import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import signup_service as s

class SignupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        s.DB_PATH=str(Path(self.temp.name)/'test.db')
        s.MAIL_TRANSPORT='preview'
        s.MAIL_PREVIEW_DIR=str(Path(self.temp.name)/'mail')
        s.PUBLIC_URL='http://127.0.0.1:8765'
        s.BETA_INVITE_ORIGIN=''
        s.ADMIN_SECRET='test-admin-secret'
        s.SURVEY_TOKENS.clear()
        for limit in s.LIMITS.values(): limit.hits.clear()
        s.init_db()
        self.server=s.ThreadingHTTPServer(('127.0.0.1',0),s.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.temp.cleanup()

    def post(self,path,data,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**(headers or {})})
        # The service answers before its database transaction commits, so give it a moment to finish.
        try:
            with urllib.request.urlopen(req) as res: out=res.status,json.loads(res.read() or b'{}')
        except urllib.error.HTTPError as err: out=err.code,json.loads(err.read())
        time.sleep(0.05)
        return out

    def query(self,sql,args=()):
        with s.db() as c: return [dict(r) for r in c.execute(sql,args)]

    def subscribe(self,email='member@example.test',newsletter=True,beta=False):
        code,body=self.post('/api/subscribe',dict(email=email,newsletter=newsletter,beta=beta,consent=True))
        self.assertEqual(code,200,body)
        return self.query('SELECT * FROM preference_requests ORDER BY rowid DESC')[0]['token']

    def confirm(self,token):
        code,body=self.post('/api/confirm',dict(token=token));self.assertEqual(code,200,body)

    def test_preferences_are_separate_and_confirmation_is_required(self):
        for index,(newsletter,beta) in enumerate([(True,False),(False,True),(True,True)]):
            email=f'member{index}@example.test'
            token=self.subscribe(email,newsletter,beta)
            row=self.query('SELECT * FROM subscribers WHERE email=?',(email,))[0]
            self.assertEqual((row['newsletter'],row['beta'],row['confirmed_at']),(0,0,None))
            self.confirm(token)
            row=self.query('SELECT * FROM subscribers WHERE email=?',(email,))[0]
            self.assertEqual((row['newsletter'],row['beta']),(newsletter,beta))
            self.assertTrue(row['confirmed_at'])
            self.confirm(token)

    def test_duplicate_and_unverified_preference_changes(self):
        token=self.subscribe();self.confirm(token)
        old=self.query('SELECT * FROM subscribers')[0]
        self.subscribe()
        self.assertEqual(len(self.query('SELECT * FROM outbox')),1)
        # A new choice never changes consent without inbox confirmation.
        self.post('/api/subscribe',dict(email=old['email'],newsletter=False,beta=True,consent=True))
        self.assertEqual(self.query('SELECT newsletter,beta FROM subscribers')[0],dict(newsletter=1,beta=0))
        with s.db() as c:c.execute('UPDATE subscribers SET last_mail_at=0')
        new=self.subscribe(newsletter=False,beta=True)
        self.assertNotEqual(new,token)
        self.assertEqual(self.post('/api/confirm',dict(token=token))[0],404)
        self.confirm(new)
        self.assertEqual(self.query('SELECT newsletter,beta FROM subscribers')[0],dict(newsletter=0,beta=1))

    def test_newsletter_unsubscribe_preserves_beta_and_blocks_queued_mail(self):
        self.confirm(self.subscribe(newsletter=True,beta=True))
        row=self.query('SELECT * FROM subscribers')[0]
        with s.db() as c: self.assertEqual(s.queue_newsletter(c,'update-1','Building DopeHub','Here is our progress.'),1)
        mail=self.query("SELECT * FROM outbox WHERE kind='newsletter'")[0]
        self.assertEqual(self.post('/api/unsubscribe',dict(token=row['newsletter_token']))[0],200)
        self.assertEqual(self.query('SELECT newsletter,beta FROM subscribers')[0],dict(newsletter=0,beta=1))
        self.assertFalse(s.delivery_allowed(mail))
        self.assertEqual(self.query("SELECT * FROM outbox WHERE kind='newsletter'"),[])
        self.assertEqual(self.post('/api/unsubscribe',dict(token=row['newsletter_token']))[0],200)

    def test_beta_cancellation_preserves_newsletter(self):
        self.confirm(self.subscribe(newsletter=True,beta=True))
        row=self.query('SELECT * FROM subscribers')[0]
        self.post('/api/unsubscribe',dict(token=row['beta_token']))
        self.assertEqual(self.query('SELECT newsletter,beta FROM subscribers')[0],dict(newsletter=1,beta=0))

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'preview/before-signup_service.py').exists(),'legacy fixture is not part of this repository')
    def test_legacy_migration_and_existing_links_are_preserved(self):
        # Use the actual previous schema/migrations, with synthetic records only.
        import importlib.util
        old_path=Path(__file__).resolve().parents[1]/'preview/before-signup_service.py'
        spec=importlib.util.spec_from_file_location('old_service',old_path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        legacy=str(Path(self.temp.name)/'legacy.db');old.DB_PATH=legacy;old.init_db()
        token='legacy_token_that_must_stay_valid'
        with old.db() as c:
            c.execute('INSERT INTO subscribers(email,consent_version,created_at,token) VALUES (?,?,?,?)',('legacy@example.test','2026-09-updates',s.now(),token))
            c.execute("INSERT INTO applications(name,email,role,availability,message,consent_version,created_at) VALUES ('Existing volunteer','volunteer@example.test','writer','1-3','Existing application to preserve','2026-09-updates',?)",(s.now(),))
        s.DB_PATH=legacy;s.init_db();s.init_db()
        self.assertEqual(self.query('SELECT token,newsletter,beta FROM subscribers')[0],dict(token=token,newsletter=1,beta=1))
        self.assertEqual(len(self.query('SELECT * FROM applications')),1)
        self.confirm(token)
        self.assertEqual(self.post('/api/unsubscribe',dict(token=token))[0],200)
        self.assertEqual(self.query('SELECT * FROM subscribers'),[])
        self.assertEqual(len(self.query('SELECT * FROM applications')),1)

    def test_invitation_requires_real_configured_origin_and_confirmed_beta(self):
        self.confirm(self.subscribe(newsletter=False,beta=True))
        # Reserved test origin is used only in this isolated fixture, never in release config.
        with s.db() as c:
            with self.assertRaises(ValueError):s.queue_invitation(c,'member@example.test','https://beta.example.test/invite/test','beta-1')
            s.BETA_INVITE_ORIGIN='https://beta.example.test'
            with self.assertRaises(ValueError):s.queue_invitation(c,'member@example.test','https://evil.example.test/invite/test','beta-1')
            self.assertTrue(s.queue_invitation(c,'member@example.test','https://beta.example.test/invite/test','beta-1'))
            self.assertFalse(s.queue_invitation(c,'member@example.test','https://beta.example.test/invite/test','beta-1'))
            self.assertEqual(s.queue_newsletter(c,'news-1','News','An update'),0)
        row=self.query("SELECT * FROM outbox WHERE kind='beta_invite'")[0]
        self.assertIn('https://beta.example.test/invite/test',row['text_body'])
        self.assertNotIn('?confirm=',row['text_body'])

    def test_newsletter_launch_and_preview_headers(self):
        self.confirm(self.subscribe())
        with s.db() as c:
            self.assertEqual(s.queue_newsletter(c,'launch-1','A launch update','A sample update.','launch'),1)
            self.assertEqual(s.queue_newsletter(c,'launch-1','A launch update','A sample update.','launch'),0)
        row=self.query("SELECT * FROM outbox WHERE kind='launch'")[0]
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network in preview')),patch('smtplib.SMTP',side_effect=AssertionError('No SMTP')):
            s.send_mail(row)
        file=next(Path(s.MAIL_PREVIEW_DIR).glob('*.json'));data=json.loads(file.read_text())
        self.assertEqual(data['from'],'no-reply@dopehub.net');self.assertEqual(data['replyTo'],'contact@dopehub.net')
        self.assertEqual(data['fromName'],'DopeHub Newsletter')
        self.assertIn('?unsubscribe=',data['text'])

    def test_application_is_stored_with_staff_notification_and_acknowledgement(self):
        payload=dict(name='Test Volunteer',email='volunteer@example.test',role='writer',availability='1-3',message='I can help write and carefully check community guides.',consent=True)
        code,body=self.post('/api/apply',payload);self.assertEqual(code,200,body)
        self.assertEqual(len(self.query('SELECT * FROM applications')),1)
        self.assertEqual(self.query('SELECT * FROM subscribers'),[])
        rows=self.query('SELECT * FROM outbox ORDER BY id')
        self.assertEqual([r['kind'] for r in rows],['alert','application_ack'])
        self.assertEqual(rows[0]['to_addr'],'contact@dopehub.net')
        self.assertEqual(rows[1]['to_addr'],payload['email'])
        for row in rows:self.assertEqual(row['reply_to'],'contact@dopehub.net')
        self.assertEqual(self.post('/admin/api/applications/1',{'status':'contacted'})[0],403)
        self.assertEqual(self.post('/admin/api/applications/1',{'status':'contacted'},{'X-Admin-Secret':s.ADMIN_SECRET})[0],200)

    def test_validation_expiry_rate_limit_and_origin(self):
        for data in [dict(email='bad',newsletter=True,beta=False),dict(email='valid@example.test',newsletter=False,beta=False),dict(email='valid@example.test',newsletter='yes',beta=False)]:
            self.assertEqual(self.post('/api/subscribe',dict(consent=True,**data))[0],400)
        payload=dict(email='valid@example.test',newsletter=True,beta=False,consent=True)
        self.assertEqual(self.post('/api/subscribe',payload,{'Origin':'https://untrusted.example'})[0],403)
        token=self.subscribe()
        with s.db() as c:c.execute('UPDATE preference_requests SET expires_at=0')
        self.assertEqual(self.post('/api/confirm',dict(token=token))[0],400)
        self.post('/api/subscribe',payload);self.post('/api/subscribe',payload)
        self.assertEqual(self.post('/api/subscribe',payload)[0],429)

    def test_rfc8058_one_click_unsubscribe(self):
        self.confirm(self.subscribe(newsletter=True,beta=True));row=self.query('SELECT * FROM subscribers')[0]
        req=urllib.request.Request(self.base+'/api/unsubscribe?t='+row['newsletter_token'],data=b'List-Unsubscribe=One-Click',headers={'Content-Type':'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req) as res:self.assertEqual(res.status,200)
        self.assertEqual(self.query('SELECT newsletter,beta FROM subscribers')[0],dict(newsletter=0,beta=1))

    def test_withdrawing_last_preference_removes_signup(self):
        self.confirm(self.subscribe())
        row=self.query('SELECT * FROM subscribers')[0]
        self.post('/api/unsubscribe',dict(token=row['newsletter_token']))
        self.assertEqual(self.query('SELECT * FROM subscribers'),[])
        self.assertEqual(self.query('SELECT * FROM preference_requests'),[])

    def test_relay_and_smtp_sender_contract(self):
        self.confirm(self.subscribe())
        with s.db() as c:s.queue_newsletter(c,'sender-check','A community update','Preview content')
        row=self.query("SELECT * FROM outbox WHERE kind='newsletter'")[0]
        s.MAIL_TRANSPORT='relay';s.RELAY_URL='https://relay.example.test/email';s.RELAY_TOKEN='test-token'
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"status":"sent"}'
        with patch('urllib.request.urlopen',return_value=response) as send:
            s.send_mail(row)
            payload=json.loads(send.call_args.args[0].data)
            self.assertEqual(payload['from'],'no-reply@dopehub.net')
            self.assertEqual(payload['replyTo'],'contact@dopehub.net')
            self.assertEqual(payload['fromName'],'DopeHub Newsletter')
            self.assertIn('/api/unsubscribe?t=',payload['listUnsubscribe'])
        s.MAIL_TRANSPORT='smtp';s.SMTP_SECURITY='ssl';s.SMTP_USER=''
        with patch('smtplib.SMTP_SSL') as smtp:
            s.send_mail(row)
            msg=smtp.return_value.send_message.call_args.args[0]
            self.assertEqual(str(msg['Reply-To']),'contact@dopehub.net')
            self.assertIn('no-reply@dopehub.net',str(msg['From']))
            self.assertEqual(str(msg['List-Unsubscribe-Post']),'List-Unsubscribe=One-Click')

if __name__=='__main__':unittest.main(verbosity=2)
