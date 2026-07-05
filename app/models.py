from datetime import datetime, timezone
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='user')  # 'admin' or 'user'
    account_status = db.Column(db.String(16), nullable=False, default='active')  # draft, pending, active, suspended
    profile_complete = db.Column(db.Boolean, default=False, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=True)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    display_name = db.Column(db.String(120), nullable=True)
    requested_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    requested_member_role = db.Column(db.String(32), nullable=True)
    review_action = db.Column(db.String(16), nullable=True)
    review_reason = db.Column(db.Text, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    requested_team = db.relationship('Team', foreign_keys=[requested_team_id], lazy='joined')
    review_events = db.relationship(
        'UserReviewEvent',
        foreign_keys='UserReviewEvent.user_id',
        backref='target_user',
        lazy=True,
        cascade='all, delete-orphan',
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def can_login(self):
        return self.is_active and self.account_status in {'draft', 'pending', 'active'}

    def auth_claims(self):
        memberships = [
            membership.claim()
            for membership in self.memberships
            if membership.is_active
        ]
        pending_memberships = [
            membership.claim()
            for membership in self.memberships
            if not membership.is_active
        ]
        return {
            'profile_complete': self.profile_complete,
            'account_status': self.account_status,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'display_name': self.full_name,
            'email': self.email,
            'memberships': memberships,
            'pending_memberships': pending_memberships,
            'teams': sorted({membership['team_code'] for membership in memberships if membership.get('team_code')}),
            'member_roles': sorted({membership['member_role'] for membership in memberships if membership.get('member_role')}),
        }

    @property
    def full_name(self):
        name = ' '.join(part for part in (self.first_name, self.last_name) if part)
        return name or self.display_name or self.username

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
    internal_url = db.Column(db.String(255), nullable=True)  # Service-zu-Service URL
    icon = db.Column(db.String(64), default='grid')  # Bootstrap Icons name
    description = db.Column(db.String(255), default='')
    required_role = db.Column(db.String(16), default='user')  # 'admin' or 'user'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<Service {self.name}>'


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<Team {self.code}>'


class MemberRole(db.Model):
    __tablename__ = 'member_roles'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(32), unique=True, nullable=False, index=True)
    label = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<MemberRole {self.key}>'


class RolePermission(db.Model):
    __tablename__ = 'role_permissions'
    __table_args__ = (
        db.UniqueConstraint('member_role_key', 'service_name', 'permission_key', name='uq_role_permission_triplet'),
    )

    id = db.Column(db.Integer, primary_key=True)
    member_role_key = db.Column(db.String(32), nullable=False, index=True)
    service_name = db.Column(db.String(64), nullable=False, default='*', index=True)
    permission_key = db.Column(db.String(64), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<RolePermission {self.member_role_key}:{self.service_name}:{self.permission_key}>'


class TeamMembership(db.Model):
    __tablename__ = 'team_memberships'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'team_id', 'member_role', name='uq_user_team_member_role'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    member_role = db.Column(db.String(32), nullable=False, default='player')  # player, coach, head_coach
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', backref=db.backref('memberships', lazy=True, cascade='all, delete-orphan'))
    team = db.relationship('Team', backref=db.backref('memberships', lazy=True, cascade='all, delete-orphan'))

    def claim(self):
        return {
            'team_id': self.team_id,
            'team_code': self.team.code if self.team else None,
            'team_name': self.team.name if self.team else None,
            'member_role': self.member_role,
        }

    def __repr__(self):
        return f'<TeamMembership user={self.user_id} team={self.team_id} role={self.member_role}>'


class UserReviewEvent(db.Model):
    __tablename__ = 'user_review_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    action = db.Column(db.String(16), nullable=False)  # approved, rejected
    reason = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(32), nullable=False, default='manual')  # users_ui, team_manager_api
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    reviewer = db.relationship('User', foreign_keys=[reviewed_by_user_id])

    def __repr__(self):
        return f'<UserReviewEvent user={self.user_id} action={self.action} source={self.source}>'
