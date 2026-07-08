import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('SQLALCHEMY_DATABASE_URI')
        or os.environ.get('DATABASE_URL')
        or 'postgresql+psycopg://tt_auth:tt_auth_password@tt-postgres-auth:5432/tt_auth'
    )
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
    DEFAULT_MEMBERS_URL = os.environ.get('DEFAULT_MEMBERS_URL', 'http://localhost:8088')
    DEFAULT_AGENDA_URL = os.environ.get('DEFAULT_AGENDA_URL', 'http://localhost:8086')
    DEFAULT_ANALYTICS_URL = os.environ.get('DEFAULT_ANALYTICS_URL', 'http://localhost:8087')
    DEFAULT_INFRA_URL = os.environ.get('DEFAULT_INFRA_URL', 'http://localhost:8084')
    DEFAULT_MEMBERS_INTERNAL_URL = os.environ.get('DEFAULT_MEMBERS_INTERNAL_URL', 'http://host.docker.internal:8088')
    DEFAULT_AGENDA_INTERNAL_URL = os.environ.get('DEFAULT_AGENDA_INTERNAL_URL', 'http://host.docker.internal:8086')
    DEFAULT_ANALYTICS_INTERNAL_URL = os.environ.get('DEFAULT_ANALYTICS_INTERNAL_URL', 'http://host.docker.internal:8087')
    DEFAULT_INFRA_INTERNAL_URL = os.environ.get('DEFAULT_INFRA_INTERNAL_URL', 'http://host.docker.internal:8084')
    DEFAULT_ATTENDANCE_URL = os.environ.get('DEFAULT_ATTENDANCE_URL', 'http://localhost:8089')
    DEFAULT_ATTENDANCE_INTERNAL_URL = os.environ.get('DEFAULT_ATTENDANCE_INTERNAL_URL', 'http://host.docker.internal:8089')
    TT_MEMBERS_INTERNAL_URL = os.environ.get('TT_MEMBERS_INTERNAL_URL')
    TT_INFRA_INTERNAL_URL = os.environ.get('TT_INFRA_INTERNAL_URL')
    SSO_SHARED_SECRET = os.environ.get('SSO_SHARED_SECRET') or SECRET_KEY
    SSO_TOKEN_EXPIRY_SECONDS = int(os.environ.get('SSO_TOKEN_EXPIRY_SECONDS', 60))
    INTERNAL_API_SECRET = os.environ.get('INTERNAL_API_SECRET') or 'tt-internal-dev-secret-change-me'
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
