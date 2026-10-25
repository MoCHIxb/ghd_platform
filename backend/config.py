import os
from datetime import timedelta


class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # 数据库：本地开发默认使用免安装 SQLite；部署时可通过 DATABASE_URL
    # 或 DB_BACKEND=mysql + DB_* 环境变量切换到 MySQL。
    DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
    DB_PORT = os.environ.get('DB_PORT', '3306')
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASS = os.environ.get('DB_PASS', 'password')
    DB_NAME = os.environ.get('DB_NAME', 'ghd_platform')
    DATABASE_URL = os.environ.get('DATABASE_URL')
    DB_BACKEND = os.environ.get('DB_BACKEND', 'sqlite').lower()
    SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ghd_platform.db')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or (
        f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
        if DB_BACKEND == 'mysql'
        else f"sqlite:///{SQLITE_PATH.replace(os.sep, '/')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }

    # JWT
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-dev-secret-change-in-production-now')
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
