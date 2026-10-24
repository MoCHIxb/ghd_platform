import os
from datetime import timedelta


class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # MySQL
    DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
    DB_PORT = os.environ.get('DB_PORT', '3306')
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASS = os.environ.get('DB_PASS', 'password')
    DB_NAME = os.environ.get('DB_NAME', 'ghd_platform')
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{os.environ.get('DB_USER', 'root')}:"
        f"{os.environ.get('DB_PASS', 'password')}@"
        f"{os.environ.get('DB_HOST', '127.0.0.1')}:"
        f"{os.environ.get('DB_PORT', '3306')}/"
        f"{os.environ.get('DB_NAME', 'ghd_platform')}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }

    # JWT
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

    # File upload
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2 GB

    ALLOWED_AUDIO = {'mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a'}
    ALLOWED_VIDEO = {'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'}
    ALLOWED_IMAGE = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ALLOWED_DOCUMENT = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'md', 'zip'}

    @classmethod
    def allowed_extensions(cls):
        return cls.ALLOWED_AUDIO | cls.ALLOWED_VIDEO | cls.ALLOWED_IMAGE | cls.ALLOWED_DOCUMENT
