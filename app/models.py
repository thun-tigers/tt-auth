from datetime import datetime, timezone
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='user')  # 'admin' or 'user'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class ServiceAccess(db.Model):
    __tablename__ = 'service_access'
    __table_args__ = (db.UniqueConstraint('user_id', 'service_id', name='uq_user_service_access'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='user')
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', backref=db.backref('service_access', lazy=True, cascade='all, delete-orphan'))
    service = db.relationship('Service', backref=db.backref('user_access', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<ServiceAccess user={self.user_id} service={self.service_id} role={self.role}>'


class Service(db.Model):
    __tablename__ = 'services'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    url = db.Column(db.String(255), nullable=False)
    icon = db.Column(db.String(64), default='grid')  # Bootstrap Icons name
    description = db.Column(db.String(255), default='')
    required_role = db.Column(db.String(16), default='user')  # 'admin' or 'user'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<Service {self.name}>'
