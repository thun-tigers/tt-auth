import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///auth.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_EXPIRY_HOURS = int(os.environ.get('JWT_EXPIRY_HOURS', 8))
    JWT_COOKIE_NAME = 'tt_jwt'
    JWT_COOKIE_DOMAIN = os.environ.get('JWT_COOKIE_DOMAIN', None)
    JWT_COOKIE_SECURE = os.environ.get('JWT_COOKIE_SECURE', 'false').lower() == 'true'
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
    AUTO_CREATE_DB = os.environ.get('AUTO_CREATE_DB', 'true').lower() == 'true'
    CREATE_DEFAULT_USERS = os.environ.get('CREATE_DEFAULT_USERS', 'true').lower() == 'true'
    CREATE_DEFAULT_SERVICES = os.environ.get('CREATE_DEFAULT_SERVICES', 'true').lower() == 'true'
    DEFAULT_ADMIN_USERNAME = os.environ.get('DEFAULT_ADMIN_USERNAME', 'admin')
    DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'admin')
    DEFAULT_AGENDA_URL = os.environ.get('DEFAULT_AGENDA_URL', 'http://localhost:8085')
    SSO_SHARED_SECRET = os.environ.get('SSO_SHARED_SECRET') or SECRET_KEY
    SSO_TOKEN_EXPIRY_SECONDS = int(os.environ.get('SSO_TOKEN_EXPIRY_SECONDS', 60))
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
