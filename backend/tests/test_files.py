import os
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta, datetime
from io import BytesIO

import bcrypt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from config import Config
from extensions import db
from models import Department, Role, User
from utils.file_helper import sanitize_original_name


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    JWT_SECRET_KEY = 'files-test-key-at-least-32-characters'


class FileNameSanitizeTest(unittest.TestCase):
    """原始文件名净化：必须保留中文，同时拦住路径穿越和非法扩展名。"""

    def test_keeps_chinese_name_and_extension(self):
        """中文主体原样保留，扩展名统一规范成小写。"""
        for raw, name, ext in [
            ('升旗照片.jpg', '升旗照片.jpg', 'jpg'),
            ('封面.png', '封面.png', 'png'),
            ('头像.png', '头像.png', 'png'),
            ('队旗.JPG', '队旗.jpg', 'jpg'),
            ('活动方案.pdf', '活动方案.pdf', 'pdf'),
            ('activity.png', 'activity.png', 'png'),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_original_name(raw), (name, ext))

    def test_strips_path_traversal(self):
        for raw in ('../../etc/passwd', '..\\..\\windows\\system32\\x.jpg'):
            with self.subTest(raw=raw):
                name, _ = sanitize_original_name(raw)
                self.assertNotIn('..', name)
                self.assertNotIn('/', name)
                self.assertNotIn('\\', name)

    def test_rejects_non_whitelisted_extension(self):
        _, ext = sanitize_original_name('木马.exe')
        self.assertEqual(ext, 'exe')
        self.assertNotIn(ext, Config.allowed_extensions())

    def test_handles_empty_and_extensionless(self):
        self.assertEqual(sanitize_original_name(''), ('', ''))
        self.assertEqual(sanitize_original_name('   '), ('', ''))
        self.assertEqual(sanitize_original_name('无扩展名'), ('无扩展名', ''))

    def test_strips_bidi_and_control_characters(self):
        """双向控制符可伪造界面显示的扩展名，控制字符可注入换行，都必须清掉。"""
        name, ext = sanitize_original_name('报告\u202epng.docx')
        self.assertNotIn('\u202e', name)
        self.assertEqual(ext, 'docx')
        name, _ = sanitize_original_name('照片\x00.jpg\nX-Inject: 1')
        self.assertNotIn('\x00', name)
        self.assertNotIn('\n', name)

    def test_long_name_truncated_to_fit_column(self):
        """original_name 落库字段是 String(255)，超长必须截断。"""
        name, ext = sanitize_original_name('a' * 400 + '.jpg')
        self.assertLessEqual(len(name), 255)
        self.assertEqual(ext, 'jpg')


class FileFlowTest(unittest.TestCase):
    """上传 -> 活动素材 -> 办公室归档 -> 下载 的完整链路。"""

    def setUp(self):
        self.app = create_app(TestConfig)
        self.upload_dir = tempfile.mkdtemp(prefix='ghd-files-test-')
        self.app.config['UPLOAD_FOLDER'] = self.upload_dir
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        department = Department(department_name='综合办公室', sort_order=1)
        captain_role, member_role = Role(role_name='captain'), Role(role_name='member')
        password_hash = bcrypt.hashpw(b'password', bcrypt.gensalt()).decode()
        captain = User(username='captain', email='captain@test.local',
                       password_hash=password_hash, status=1)
        captain.roles.append(captain_role)
        db.session.add_all([department, captain_role, member_role, captain])
        db.session.commit()

        self.client = self.app.test_client()
        response = self.client.post('/api/auth/login', json={
            'username': 'captain', 'password': 'password'})
        self.token = response.get_json()['token']
        self.headers = {'Authorization': 'Bearer ' + self.token}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def _upload(self, filename, content=b'fake-bytes', visibility='1'):
        return self.client.post('/api/files/upload', headers=self.headers, data={
            'file': (BytesIO(content), filename),
            'visibility': visibility,
            'description': '测试文件',
        }, content_type='multipart/form-data')

    def _create_activity(self, title='周一升旗'):
        start = datetime.now() + timedelta(days=1)
        return self.client.post('/api/club/activities', headers=self.headers, json={
            'title': title, 'activity_type': '升旗', 'start_time': start.isoformat()})

    def test_upload_preserves_chinese_metadata(self):
        response = self._upload('升旗照片.jpg')
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()['file']
        self.assertEqual(payload['original_name'], '升旗照片.jpg')
        self.assertEqual(payload['file_ext'], 'jpg')
        self.assertEqual(payload['file_type'], 'image')
        stored = [name for name in os.listdir(self.upload_dir) if os.path.isfile(
            os.path.join(self.upload_dir, name))]
        self.assertEqual(len(stored), 1)
        self.assertTrue(stored[0].endswith('.jpg'), stored)

    def test_rejects_extension_outside_whitelist(self):
        self.assertEqual(self._upload('木马.exe').status_code, 415)

    def test_chinese_cover_no_longer_rejected(self):
        """回归：封面图使用中文名时曾被 secure_filename 判成"图片格式不合法"。"""
        response = self.client.post('/api/club/activities', headers=self.headers, data={
            'title': '带中文封面的活动', 'activity_type': '升旗',
            'start_time': (datetime.now() + timedelta(days=1)).isoformat(),
            'cover': (BytesIO(b'\x89PNG fake'), '升旗封面.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        cover_url = response.get_json()['activity']['cover_url']
        self.assertTrue(cover_url.endswith('.png'))
        self.assertEqual(self.client.get(cover_url).status_code, 200)

    def test_chinese_avatar_no_longer_rejected(self):
        response = self.client.post('/api/auth/avatar', headers=self.headers, data={
            'avatar': (BytesIO(b'\x89PNG fake'), '我的头像.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)

    def test_media_submission_and_archive_chain(self):
        activity_id = self._create_activity().get_json()['activity']['activity_id']
        file_id = self._upload('升旗现场视频.mp4').get_json()['file']['file_id']

        submitted = self.client.post(f'/api/club/activities/{activity_id}/media',
                                     headers=self.headers, json={'file_id': file_id})
        self.assertEqual(submitted.status_code, 201)
        duplicated = self.client.post(f'/api/club/activities/{activity_id}/media',
                                      headers=self.headers, json={'file_id': file_id})
        self.assertEqual(duplicated.status_code, 409)
        missing = self.client.post(f'/api/club/activities/{activity_id}/media',
                                   headers=self.headers, json={'file_id': 999999})
        self.assertEqual(missing.status_code, 404)

        detail = self.client.get(f'/api/club/activities/{activity_id}',
                                 headers=self.headers).get_json()
        self.assertEqual(len(detail['media']), 1)
        self.assertEqual(detail['media'][0]['file']['original_name'], '升旗现场视频.mp4')
        self.assertEqual(detail['media'][0]['review_status'], '待审阅')

        queue = self.client.get('/api/club/office/media', headers=self.headers).get_json()
        media_id = queue['media'][0]['media_id']
        reviewed = self.client.put(f'/api/club/office/media/{media_id}/review',
                                   headers=self.headers,
                                   json={'review_status': '已通过', 'review_comment': '可用'})
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.get_json()['media']['review_status'], '已通过')

        archived = self.client.post('/api/club/office/archives', headers=self.headers, json={
            'title': '2026 春季升旗档案', 'archive_type': '宣传材料', 'file_id': file_id})
        self.assertEqual(archived.status_code, 201)
        archives = self.client.get('/api/club/office/archives',
                                   headers=self.headers).get_json()['archives']
        self.assertEqual(archives[0]['file']['original_name'], '升旗现场视频.mp4')

    def test_media_submission_rejects_malformed_file_id(self):
        """回归：file_id 缺失时 Query.get(None) 会抛 InvalidRequestError 变成 500。"""
        activity_id = self._create_activity().get_json()['activity']['activity_id']
        for payload in ({}, {'file_id': None}, {'file_id': 'abc'}, {'file_id': []}):
            with self.subTest(payload=payload):
                response = self.client.post(f'/api/club/activities/{activity_id}/media',
                                            headers=self.headers, json=payload)
                self.assertEqual(response.status_code, 400)

    def test_archive_rejects_malformed_file_id(self):
        """归档接口同样不能因为 file_id 缺失而 500。"""
        for payload in ({}, {'file_id': None}, {'file_id': 'abc'}):
            with self.subTest(payload=payload):
                body = {'title': '测试档案', 'archive_type': '制度文件'}
                body.update(payload)
                response = self.client.post('/api/club/office/archives',
                                            headers=self.headers, json=body)
                self.assertEqual(response.status_code, 400)

    def test_download_returns_utf8_filename(self):
        file_id = self._upload('升旗照片.jpg').get_json()['file']['file_id']
        response = self.client.get(f'/api/files/{file_id}/download?token={self.token}')
        self.assertEqual(response.status_code, 200)
        disposition = response.headers.get('Content-Disposition', '')
        self.assertIn("filename*=UTF-8''", disposition)
        response.close()

    def test_change_password(self):
        wrong = self.client.put('/api/auth/password', headers=self.headers, json={
            'old_password': 'not-my-password', 'new_password': 'NewPass@2026'})
        self.assertEqual(wrong.status_code, 401)
        changed = self.client.put('/api/auth/password', headers=self.headers, json={
            'old_password': 'password', 'new_password': 'NewPass@2026'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.post('/api/auth/login', json={
            'username': 'captain', 'password': 'password'}).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', json={
            'username': 'captain', 'password': 'NewPass@2026'}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
