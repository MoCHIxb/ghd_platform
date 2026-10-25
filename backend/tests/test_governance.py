import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

import bcrypt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from config import Config
from extensions import db
from models import Department, Role, User


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    JWT_SECRET_KEY = 'governance-test-key-at-least-32-characters'


class GovernanceApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.upload_dir = tempfile.mkdtemp(prefix='ghd-governance-test-')
        self.app.config['UPLOAD_FOLDER'] = self.upload_dir
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        office = Department(department_name='综合办公室', sort_order=1)
        instructor = Department(department_name='教官部', sort_order=2)
        logistics = Department(department_name='后勤部', sort_order=3)
        member_role = Role(role_name='member')
        minister_role = Role(role_name='minister')
        captain_role = Role(role_name='captain')
        password_hash = bcrypt.hashpw(b'password', bcrypt.gensalt()).decode()

        captain = User(username='captain', email='captain@test.local',
                       password_hash=password_hash, status=1)
        captain.roles.extend([member_role, captain_role])
        minister = User(username='office_minister', email='minister@test.local',
                        password_hash=password_hash, status=1, department=office)
        minister.roles.extend([member_role, minister_role])
        member = User(username='member', email='member@test.local', real_name='申请社员',
                      password_hash=password_hash, status=1)
        member.roles.append(member_role)
        colleague = User(username='colleague', email='colleague@test.local', real_name='接任社员',
                         password_hash=password_hash, status=1, department=office)
        colleague.roles.append(member_role)
        db.session.add_all([
            office, instructor, logistics, member_role, minister_role, captain_role,
            captain, minister, member, colleague,
        ])
        db.session.commit()
        self.office_id = office.department_id
        self.member_id = member.user_id
        self.colleague_id = colleague.user_id
        self.client = self.app.test_client()
        self.captain_headers = self._login('captain')
        self.minister_headers = self._login('office_minister')
        self.member_headers = self._login('member')
        self.colleague_headers = self._login('colleague')

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def _login(self, username, password='password'):
        response = self.client.post('/api/auth/login', json={
            'username': username, 'password': password,
        })
        self.assertEqual(response.status_code, 200)
        return {'Authorization': 'Bearer ' + response.get_json()['token']}

    def test_registration_and_deactivation_approval(self):
        registered = self.client.post('/api/auth/register', json={
            'username': 'new_member', 'password': 'newpass',
            'email': 'new@test.local', 'real_name': '新社员', 'student_no': '2026001',
        })
        self.assertEqual(registered.status_code, 201)
        blocked = self.client.post('/api/auth/login', json={
            'username': 'new_member', 'password': 'newpass',
        })
        self.assertEqual(blocked.status_code, 403)
        dashboard = self.client.get('/api/governance/dashboard',
                                    headers=self.captain_headers).get_json()
        request_id = dashboard['membership_requests'][0]['request_id']
        approved = self.client.put(
            f'/api/governance/membership-requests/{request_id}/review',
            headers=self.captain_headers, json={'approved': True})
        self.assertEqual(approved.status_code, 200)
        new_headers = self._login('new_member', 'newpass')
        requested = self.client.post('/api/governance/deactivation-request',
                                     headers=new_headers, json={'reason': '毕业离队'})
        self.assertEqual(requested.status_code, 201)
        request_id = requested.get_json()['request']['request_id']
        removed = self.client.put(
            f'/api/governance/membership-requests/{request_id}/review',
            headers=self.captain_headers, json={'approved': True})
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.post('/api/auth/login', json={
            'username': 'new_member', 'password': 'newpass',
        }).status_code, 403)

    def test_department_dual_approval_and_temporary_edit(self):
        denied = self.client.post('/api/club/office/socials', headers=self.member_headers,
                                  json={'platform': '测试', 'account_name': '账号',
                                        'link_url': 'https://example.com'})
        self.assertEqual(denied.status_code, 403)
        applied = self.client.post('/api/governance/department-applications',
                                   headers=self.member_headers,
                                   json={'department_id': self.office_id, 'reason': '申请加入'})
        app_id = applied.get_json()['application']['application_id']
        captain_review = self.client.put(
            f'/api/governance/department-applications/{app_id}/review',
            headers=self.captain_headers, json={'approved': True})
        self.assertEqual(captain_review.get_json()['application']['status'], '待审核')
        minister_review = self.client.put(
            f'/api/governance/department-applications/{app_id}/review',
            headers=self.minister_headers, json={'approved': True})
        self.assertEqual(minister_review.get_json()['application']['status'], '已通过')

        expires = (datetime.now() + timedelta(days=7)).isoformat()
        granted = self.client.post('/api/governance/grants', headers=self.minister_headers,
                                   json={'user_id': self.member_id,
                                         'department_id': self.office_id,
                                         'expires_at': expires, 'reason': '宣传周协助'})
        self.assertEqual(granted.status_code, 201)
        allowed = self.client.post('/api/club/office/socials', headers=self.member_headers,
                                   json={'platform': '测试', 'account_name': '账号',
                                         'link_url': 'https://example.com'})
        self.assertEqual(allowed.status_code, 201)
        wrong_department = self.client.post('/api/club/equipment/categories',
                                            headers=self.minister_headers,
                                            json={'category_name': '不应创建'})
        self.assertEqual(wrong_department.status_code, 403)

    def test_leadership_transfer_and_named_forum(self):
        proposed = self.client.post('/api/governance/transfers',
                                    headers=self.minister_headers,
                                    json={'role_name': 'minister',
                                          'to_user_id': self.colleague_id,
                                          'note': '部长换届'})
        self.assertEqual(proposed.status_code, 201)
        transfer_id = proposed.get_json()['transfer']['transfer_id']
        accepted = self.client.put(
            f'/api/governance/transfers/{transfer_id}/respond',
            headers=self.colleague_headers, json={'accepted': True})
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(db.session.get(User, proposed.get_json()['transfer']['from_user_id']).has_role('minister'))
        self.assertTrue(db.session.get(User, self.colleague_id).has_role('minister'))

        post = self.client.post('/api/governance/forum/posts', headers=self.member_headers,
                                json={'title': '训练建议', 'content': '建议增加队列练习。'})
        self.assertEqual(post.status_code, 201)
        post_id = post.get_json()['post']['post_id']
        comment = self.client.post(
            f'/api/governance/forum/posts/{post_id}/comments',
            headers=self.colleague_headers, json={'content': '收到，会安排。'})
        self.assertEqual(comment.status_code, 201)
        rows = self.client.get('/api/governance/forum/posts',
                               headers=self.member_headers).get_json()['posts']
        self.assertEqual(rows[0]['author_name'], '申请社员')
        self.assertEqual(rows[0]['comments'][0]['author_name'], '接任社员')

    def test_captain_account_management_and_handover(self):
        denied = self.client.post('/api/governance/accounts', headers=self.member_headers,
                                  json={'username': 'forbidden', 'password': 'password',
                                        'email': 'forbidden@test.local'})
        self.assertEqual(denied.status_code, 403)
        created = self.client.post('/api/governance/accounts', headers=self.captain_headers,
                                   json={'username': 'direct_member', 'password': 'password',
                                         'email': 'direct@test.local', 'real_name': '直接创建'})
        self.assertEqual(created.status_code, 201)
        direct_id = created.get_json()['user']['user_id']
        self._login('direct_member')
        removed = self.client.delete(f'/api/governance/accounts/{direct_id}',
                                     headers=self.captain_headers, json={'reason': '测试注销'})
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.post('/api/auth/login', json={
            'username': 'direct_member', 'password': 'password',
        }).status_code, 403)

        proposed = self.client.post('/api/governance/transfers', headers=self.captain_headers,
                                    json={'role_name': 'captain',
                                          'to_user_id': self.colleague_id,
                                          'note': '队长换届'})
        self.assertEqual(proposed.status_code, 201)
        accepted = self.client.put(
            f"/api/governance/transfers/{proposed.get_json()['transfer']['transfer_id']}/respond",
            headers=self.colleague_headers, json={'accepted': True})
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(db.session.get(User, self.colleague_id).has_role('captain'))
        self.assertIsNone(db.session.get(User, self.colleague_id).department_id)


if __name__ == '__main__':
    unittest.main()
