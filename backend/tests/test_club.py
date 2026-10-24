import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO

import bcrypt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from config import Config
from extensions import db
from models import Department, Equipment, EquipmentCategory, Role, User


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    JWT_SECRET_KEY = 'test-key'


class ClubApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.upload_dir = tempfile.mkdtemp(prefix='ghd-test-')
        self.app.config['UPLOAD_FOLDER'] = self.upload_dir
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        department = Department(department_name='综合办公室', sort_order=1)
        captain_role = Role(role_name='captain')
        password_hash = bcrypt.hashpw(b'password', bcrypt.gensalt()).decode()
        captain = User(username='captain', email='captain@test.local',
                       password_hash=password_hash, department=department)
        captain.roles.append(captain_role)
        category = EquipmentCategory(category_name='仪仗装备')
        equipment = Equipment(asset_code='T-001', equipment_name='测试礼宾枪',
                              category=category, total_quantity=2, available_quantity=2)
        db.session.add_all([department, captain_role, captain, category, equipment])
        db.session.commit()
        self.client = self.app.test_client()
        response = self.client.post('/api/auth/login', json={'username': 'captain', 'password': 'password'})
        self.headers = {'Authorization': 'Bearer ' + response.get_json()['token']}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def test_activity_creation_and_overview(self):
        response = self.client.post('/api/club/activities', headers=self.headers, data={
            'title': '周一升旗', 'activity_type': '升旗',
            'start_time': (datetime.now() + timedelta(days=1)).isoformat(),
            'location': '东区田径场',
            'cover': (BytesIO(b'fake-png-content'), 'activity.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        cover_url = response.get_json()['activity']['cover_url']
        self.assertTrue(cover_url.endswith('.png'))
        cover_response = self.client.get(cover_url)
        self.assertEqual(cover_response.status_code, 200)
        cover_response.close()
        overview = self.client.get('/api/club/overview', headers=self.headers)
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.get_json()['activity_count'], 1)

    def test_equipment_conflict_and_return(self):
        first = self.client.post('/api/club/equipment/1/borrow', headers=self.headers,
                                 json={'quantity': 2})
        self.assertEqual(first.status_code, 201)
        conflict = self.client.post('/api/club/equipment/1/borrow', headers=self.headers,
                                    json={'quantity': 1})
        self.assertEqual(conflict.status_code, 409)
        returned = self.client.put('/api/club/equipment/usages/1/return', headers=self.headers, json={})
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.get_json()['usage']['status'], '已归还')

    def test_nested_equipment_categories(self):
        root = self.client.post('/api/club/equipment/categories', headers=self.headers,
                                json={'category_name': '宣传器材'})
        self.assertEqual(root.status_code, 201)
        root_id = root.get_json()['category']['category_id']
        child = self.client.post('/api/club/equipment/categories', headers=self.headers,
                                 json={'category_name': '摄影设备', 'parent_id': root_id})
        self.assertEqual(child.status_code, 201)
        tree = self.client.get('/api/club/equipment/categories', headers=self.headers).get_json()
        target = next(item for item in tree['categories'] if item['category_id'] == root_id)
        self.assertEqual(target['children'][0]['category_name'], '摄影设备')

    def test_equipment_cover_upload(self):
        response = self.client.post('/api/club/equipment', headers=self.headers, data={
            'asset_code': 'T-IMG-001', 'equipment_name': '带图设备',
            'category_id': '1', 'total_quantity': '1',
            'cover': (BytesIO(b'fake-jpeg-content'), 'equipment.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        self.assertIn('/api/club/covers/equipment/',
                      response.get_json()['equipment']['cover_url'])


if __name__ == '__main__':
    unittest.main()
