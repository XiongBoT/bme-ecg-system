from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from server import create_app


class AccountApplicationTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).resolve().parents[1]/'.test_runs';folder.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.temp.cleanup)
        self.app=create_app(self.temp.name,auth_enabled=True,cookie_secure=False)
        self.app.state.auth.create_user('admin','Administrator-test',True)
        self.public=TestClient(self.app);self.admin=TestClient(self.app)
        self.addCleanup(self.public.close);self.addCleanup(self.admin.close)
        login=self.admin.post('/api/auth/login',json=dict(username='admin',password='Administrator-test')).json()
        self.admin.headers['X-CSRF-Token']=login['csrf_token']

    def submit(self,username='candidate',**extra):
        body=dict(username=username,password='abcde',password_confirm='abcde',note='课程小组');body.update(extra)
        return self.public.post('/api/account-applications',json=body)

    def test_application_requires_approval_and_never_returns_password(self):
        response=self.submit();self.assertEqual(response.status_code,202,response.text);mid=response.json()['id']
        self.assertNotIn('abcde',response.text)
        self.assertEqual(self.public.post('/api/auth/login',json=dict(username='candidate',password='abcde')).status_code,401)
        pending=self.admin.get('/api/admin/account-applications');self.assertEqual(len(pending.json()['applications']),1)
        self.assertNotIn('password',pending.text)
        self.assertEqual(self.public.get('/api/admin/account-applications').status_code,401)
        self.assertEqual(self.public.post('/api/admin/account-applications/'+mid+'/approve',json={}).status_code,401)
        self.assertEqual(self.admin.post('/api/admin/account-applications/'+mid+'/approve',json={}).status_code,200)
        login=self.public.post('/api/auth/login',json=dict(username='candidate',password='abcde'))
        self.assertEqual(login.status_code,200);self.assertFalse(login.json()['user']['is_admin'])
        with closing(sqlite3.connect(Path(self.temp.name)/'cloud.sqlite')) as db:
            self.assertIsNone(db.execute('SELECT password_hash FROM account_applications WHERE id=?',(mid,)).fetchone()[0])

    def test_reject_duplicate_and_password_policy(self):
        self.assertEqual(self.submit(password='1234',password_confirm='1234').status_code,422)
        self.assertEqual(self.submit(password_confirm='different').status_code,422)
        response=self.submit();mid=response.json()['id']
        self.assertEqual(self.submit().status_code,409)
        self.assertEqual(self.admin.post('/api/admin/account-applications/'+mid+'/reject',json={}).status_code,200)
        self.assertEqual(self.admin.post('/api/admin/account-applications/'+mid+'/approve',json={}).status_code,409)
        self.assertEqual(self.public.post('/api/auth/login',json=dict(username='candidate',password='abcde')).status_code,401)

    def test_application_cannot_request_admin_and_is_rate_limited(self):
        self.assertEqual(self.submit(is_admin=True).status_code,422)
        for n in range(5):self.assertEqual(self.submit('candidate'+str(n)).status_code,202)
        self.assertEqual(self.submit('candidate-six').status_code,429)

    def test_review_requires_csrf_and_is_idempotent(self):
        mid=self.submit().json()['id'];path='/api/admin/account-applications/'+mid+'/approve'
        csrf=self.admin.headers.pop('X-CSRF-Token');self.assertEqual(self.admin.post(path,json={}).status_code,403)
        self.admin.headers['X-CSRF-Token']=csrf
        self.assertEqual(self.admin.post(path,json={}).status_code,200);self.assertEqual(self.admin.post(path,json={}).status_code,200)
        self.assertEqual(sum(u['username']=='candidate' for u in self.app.state.auth.users()),1)


if __name__=='__main__':unittest.main()
