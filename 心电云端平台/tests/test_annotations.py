"""Synthetic owner-only interval notes; never changes raw or model data."""
from contextlib import closing
import uuid
import unittest
import test_workflow as fixtures


class AnnotationTests(unittest.TestCase):
    login=fixtures.WorkflowTests.login
    register=fixtures.WorkflowTests.register
    complete=fixtures.WorkflowTests.complete

    def setUp(self):
        fixtures.WorkflowTests.setUp(self)
        self.complete()
        self.url='/api/sessions/mine/annotations'
        self.aid=uuid.uuid4().hex
        self.value={'start_sample':0,'end_sample':35,'kind':'note','note':'观察这一段','revision':0,'deleted':False}

    def save(self, **changes):
        return self.client.put(self.url+'/'+self.aid,json=dict(self.value,**changes))

    def test_annotation_lifecycle_conflict_and_raw_preserved(self):
        before=self.client.get('/api/sessions/mine/waveform').json()['points']
        r=self.save();self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['revision'],1)
        self.assertEqual(self.save().status_code,409)
        self.assertEqual(self.save(revision=1,note='第二次观察').json()['revision'],2)
        self.assertEqual(self.save(revision=2,deleted=True).status_code,200)
        self.assertEqual(self.client.get(self.url).json()['total'],0)
        self.assertEqual(self.client.get(self.url+'?include_deleted=true').json()['total'],1)
        self.assertEqual(self.save(revision=3,deleted=False).json()['revision'],4)
        self.assertEqual(before,self.client.get('/api/sessions/mine/waveform').json()['points'])
        with closing(self.app.state.workflow.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM annotation_events').fetchone()[0],4)

    def test_annotation_range_and_kind_validation(self):
        for changes in ({'start_sample':-1},{'end_sample':36},{'start_sample':35,'end_sample':0},
                        {'start_sample':True},{'kind':'diagnosis'},{'note':'x'*501},{'revision':-1}):
            with self.subTest(changes=changes):self.assertEqual(self.save(**changes).status_code,422)
        self.assertEqual(self.client.get(self.url+'?limit=101').status_code,422)
        self.register('receiving',self.user['id'])
        self.assertEqual(self.client.put('/api/sessions/receiving/annotations/'+self.aid,json=self.value).status_code,409)

    def test_annotation_owner_device_csrf_and_trash(self):
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.client.put(self.url+'/'+self.aid,headers={'X-CSRF-Token':''},json=self.value).status_code,403)
        self.assertEqual(self.client.get(self.url,headers=self.device).status_code,403)
        self.login('other');self.assertEqual(self.client.get(self.url).status_code,404)
        self.login('manager');self.assertEqual(self.client.get(self.url).status_code,404)
        self.assertEqual(self.client.post('/api/admin/database/records/mine/trash').status_code,200)
        self.login();self.assertEqual(self.client.get(self.url).status_code,409)
        self.login('manager');self.client.post('/api/admin/database/records/mine/restore')
        self.login();self.assertEqual(self.client.get(self.url).json()['total'],1)
