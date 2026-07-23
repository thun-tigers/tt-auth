import os
import logging
import requests
from flask import Flask, session
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config
from .db_bootstrap import schema_setup_lock
from .extensions import db, migrate, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.config.get('SECRET_KEY'):
        if app.debug or app.testing:
            app.logger.warning('SECRET_KEY is not set; running in insecure development mode.')
        else:
            raise RuntimeError('SECRET_KEY must be set in production.')

    # Logging
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
    formatter = logging.Formatter('[%(asctime)s +0000] [%(process)d] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # Blueprints
    from .routes.auth import bp as auth_bp
    from .routes.dashboard import bp as dashboard_bp
    from .routes.users import bp as users_bp
    from .routes.services import bp as services_bp
    from .routes.master_data import bp as master_data_bp
    from .routes.api import bp as api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(master_data_bp)
    app.register_blueprint(api_bp)

    # Zentrales UI-Layout aus tt-common
    from tt_common import register_shared_ui
    register_shared_ui(
        app,
        brand_label='Plattform',
        brand_icon='bi-shield-lock',
        home_endpoint='dashboard.index',
        profile_endpoint='dashboard.profile',
        logout_endpoint='auth.logout',
    )

    # Context processor: pending_users_count für Admin-Badge in allen Templates
    @app.context_processor
    def inject_pending_users_count():
        from flask import request as flask_request
        from .models import User
        try:
            count = User.query.filter(
                User.account_status.in_(['draft', 'pending']),
            ).count()
        except Exception:
            count = 0
        return {'pending_users_count': count}

    @app.context_processor
    def inject_pending_messages_count():
        return {'pending_messages_count': _fetch_pending_messages_count(app, session.get('auth_user_id'))}

    with app.app_context():
        if app.config.get('AUTO_CREATE_DB', True):
            with schema_setup_lock(db.engine):
                db.create_all()
                _ensure_lightweight_schema_updates(app)
                _seed_default_users(app)
                _seed_default_services(app)
                _seed_default_teams(app)
                _seed_default_member_roles(app)
                _seed_default_role_permissions(app)
                _bootstrap_default_user_access(app)
                _bootstrap_platform_admin_access(app)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    return app


def _fetch_pending_messages_count(app, auth_user_id):
    if not auth_user_id:
        return 0

    members_base = app.config.get('TT_MEMBERS_INTERNAL_URL') or app.config.get('DEFAULT_MEMBERS_INTERNAL_URL', 'http://tt-members:5000')
    members_base = members_base.rstrip('/')
    secret = app.config.get('INTERNAL_API_SECRET') or app.config.get('SSO_SHARED_SECRET') or app.config.get('SECRET_KEY')
    if not secret:
        return 0

    try:
        response = requests.get(
            f'{members_base}/api/internal/messages/count',
            params={'auth_user_id': auth_user_id},
            headers={'X-TT-Internal-Secret': secret},
            timeout=2,
        )
        if response.status_code != 200:
            return 0
        payload = response.json() or {}
        return max(0, int(payload.get('pending_messages_count') or 0))
    except Exception:
        return 0


def _seed_default_users(app):
    """Create default admin user if no users exist."""
    from .models import User
    if User.query.count() == 0 and app.config.get('CREATE_DEFAULT_USERS', True):
        admin_username = os.environ.get('DEFAULT_ADMIN_USERNAME', 'admin')
        admin_password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'admin')
        admin = User(username=admin_username, role='admin', is_active=True)
        admin.set_password(admin_password)
        db.session.add(admin)
        try:
            db.session.commit()
            app.logger.info(f'Default admin user "{admin_username}" created.')
        except IntegrityError:
            db.session.rollback()
            app.logger.info(f'Default admin user "{admin_username}" already exists.')


def _seed_default_services(app):
    """Create default dashboard services if they are missing."""
    if not app.config.get('CREATE_DEFAULT_SERVICES', True):
        return

    from .models import Service

    default_services = [
        {
            'name': 'members',
            'url': app.config.get('DEFAULT_MEMBERS_URL', 'http://localhost:8088'),
            'internal_url': app.config.get('DEFAULT_MEMBERS_INTERNAL_URL', 'http://host.docker.internal:8088'),
            'icon': 'person-badge',
            'description': 'Profile, Teams und Mitgliedschaften',
            'required_role': 'user',
            'sort_order': 5,
        },
        {
            'name': 'agenda',
            'url': app.config.get('DEFAULT_AGENDA_URL', 'http://localhost:8086'),
            'internal_url': app.config.get('DEFAULT_AGENDA_INTERNAL_URL', 'http://host.docker.internal:8086'),
            'icon': 'calendar-check',
            'description': 'Trainingsverwaltung und Live-Agenda',
            'required_role': 'user',
            'sort_order': 10,
        },
        {
            'name': 'analytics',
            'url': app.config.get('DEFAULT_ANALYTICS_URL', 'http://localhost:8087'),
            'internal_url': app.config.get('DEFAULT_ANALYTICS_INTERNAL_URL', 'http://host.docker.internal:8087'),
            'icon': 'bar-chart-line',
            'description': 'Spielanalyse, Scouting Reports und Videoauswertung',
            'required_role': 'user',
            'sort_order': 20,
        },
        {
            'name': 'infra',
            'url': app.config.get('DEFAULT_INFRA_URL', 'http://localhost:8084'),
            'internal_url': app.config.get('DEFAULT_INFRA_INTERNAL_URL', 'http://host.docker.internal:8084'),
            'icon': 'shield-lock',
            'description': 'Plattform-Admin, Backup und Betriebsfunktionen',
            'required_role': 'admin',
            'sort_order': 30,
        },
        {
            'name': 'attendance',
            'url': app.config.get('DEFAULT_ATTENDANCE_URL', 'http://localhost:5090'),
            'internal_url': app.config.get('DEFAULT_ATTENDANCE_INTERNAL_URL', 'http://host.docker.internal:5090'),
            'icon': 'hand-thumbs-up',
            'description': 'Trainingsanmeldung und Teilnehmerverwaltung',
            'required_role': 'user',
            'sort_order': 15,
        },
    ]

    existing_services = {
        service.name: service
        for service in Service.query.filter(
            Service.name.in_([service_data['name'] for service_data in default_services]),
        ).all()
    }

    created = []
    for service_data in default_services:
        existing = existing_services.get(service_data['name'])
        if existing:
            # Always sync url/internal_url from env vars so a backup-restore
            # with stale DB values is corrected on the next startup.
            updated = False
            for field in ('icon', 'description', 'required_role', 'sort_order'):
                new_value = service_data[field]
                if getattr(existing, field) != new_value:
                    setattr(existing, field, new_value)
                    updated = True
            for field in ('url', 'internal_url'):
                new_value = service_data[field]
                if getattr(existing, field) != new_value:
                    setattr(existing, field, new_value)
                    updated = True
                    app.logger.info('Service %s: %s updated to %s', existing.name, field, new_value)
            if updated:
                db.session.commit()
            continue
        db.session.add(Service(is_active=True, **service_data))
        created.append(service_data['name'])

    if not created:
        return

    try:
        db.session.commit()
        app.logger.info('Default services created: %s', ', '.join(created))
    except IntegrityError:
        db.session.rollback()
        app.logger.info('Default service creation raced with another worker; continuing.')


def _bootstrap_platform_admin_access(app):
    """Ensure platform admins have active admin access to every active service."""
    from .models import User, Service, ServiceAccess

    admins = User.query.filter_by(role='admin', is_active=True).all()
    services = Service.query.filter_by(is_active=True).all()
    if not admins or not services:
        return

    changed = False
    for admin in admins:
        if not admin.profile_complete or admin.account_status != 'active':
            admin.profile_complete = True
            admin.account_status = 'active'
            admin.is_active = True
            changed = True
        for service in services:
            access = ServiceAccess.query.filter_by(user_id=admin.id, service_id=service.id).first()
            if access:
                if access.role != 'admin':
                    access.role = 'admin'
                    changed = True
                if not access.is_active:
                    access.is_active = True
                    changed = True
                continue
            db.session.add(ServiceAccess(user_id=admin.id, service_id=service.id, role='admin', is_active=True))
            changed = True

    if changed:
        try:
            db.session.commit()
            app.logger.info('Bootstrapped initial service access for platform admins.')
        except IntegrityError:
            db.session.rollback()


def _bootstrap_default_user_access(app):
    """Ensure core services are available to every active account."""
    from .models import User, Service, ServiceAccess

    users = User.query.filter_by(is_active=True).all()
    services = Service.query.filter(
        Service.name.in_(['members', 'agenda', 'attendance']),
        Service.is_active.is_(True),
    ).all()
    changed = False

    for user in users:
        for service in services:
            access = ServiceAccess.query.filter_by(user_id=user.id, service_id=service.id).first()
            if access:
                if not access.is_active:
                    access.is_active = True
                    changed = True
                continue
            db.session.add(ServiceAccess(user_id=user.id, service_id=service.id, role='user', is_active=True))
            changed = True

    if changed:
        try:
            db.session.commit()
            app.logger.info('Bootstrapped Members, Agenda and Attendance access for all users.')
        except IntegrityError:
            db.session.rollback()


def _seed_default_teams(app):
    from .models import Team

    default_teams = [
        ('U13', 'U13', 10),
        ('U16', 'U16', 20),
        ('U19', 'U19', 30),
        ('SENIORS', 'Seniors', 40),
        ('ULTIMATE_FLAG', 'Ultimate Flag', 50),
    ]
    existing_codes = {
        code
        for (code,) in Team.query.with_entities(Team.code).filter(
            Team.code.in_([code for code, _, _ in default_teams]),
        ).all()
    }

    changed = False
    for code, name, sort_order in default_teams:
        if code in existing_codes:
            continue
        db.session.add(Team(code=code, name=name, sort_order=sort_order, is_active=True))
        changed = True
    if changed:
        try:
            db.session.commit()
            app.logger.info('Default teams created.')
        except IntegrityError:
            db.session.rollback()


def _seed_default_member_roles(app):
    from .models import MemberRole

    defaults = [
        ('player', 'Spieler', 10),
        ('coach', 'Coach', 20),
        ('head_coach', 'Head Coach', 30),
        ('team_manager', 'Team-Manager', 40),
        ('team_betreuer', 'Team-Betreuer', 50),
    ]

    existing_roles = {
        role.key: role
        for role in MemberRole.query.filter(
            MemberRole.key.in_([key for key, _, _ in defaults]),
        ).all()
    }

    changed = False
    for key, label, sort_order in defaults:
        role = existing_roles.get(key)
        if role:
            if role.label != label or role.sort_order != sort_order or not role.is_active:
                role.label = label
                role.sort_order = sort_order
                role.is_active = True
                changed = True
            continue
        db.session.add(MemberRole(key=key, label=label, sort_order=sort_order, is_active=True))
        changed = True

    if changed:
        try:
            db.session.commit()
            app.logger.info('Default member roles created/updated.')
        except IntegrityError:
            db.session.rollback()


def _seed_default_role_permissions(app):
    from .models import RolePermission

    defaults = [
        ('player', '*', 'read', 10),
        ('coach', '*', 'read', 20),
        ('coach', '*', 'create', 30),
        ('head_coach', '*', 'read', 40),
        ('head_coach', '*', 'create', 50),
        ('head_coach', '*', 'admin', 60),
        ('team_manager', '*', 'read', 70),
        ('team_manager', '*', 'create', 80),
        ('team_manager', '*', 'approve', 90),
        ('team_betreuer', '*', 'read', 100),
        ('team_betreuer', '*', 'create', 110),
        ('team_betreuer', '*', 'approve', 120),
    ]

    existing_permissions = {
        (item.member_role_key, item.service_name, item.permission_key): item
        for item in RolePermission.query.filter(
            RolePermission.member_role_key.in_([member_role_key for member_role_key, _, _, _ in defaults]),
        ).all()
    }

    changed = False
    for member_role_key, service_name, permission_key, sort_order in defaults:
        item = existing_permissions.get((member_role_key, service_name, permission_key))
        if item:
            if item.sort_order != sort_order or not item.is_active:
                item.sort_order = sort_order
                item.is_active = True
                changed = True
            continue
        db.session.add(RolePermission(
            member_role_key=member_role_key,
            service_name=service_name,
            permission_key=permission_key,
            sort_order=sort_order,
            is_active=True,
        ))
        changed = True

    if changed:
        try:
            db.session.commit()
            app.logger.info('Default role permissions created/updated.')
        except IntegrityError:
            db.session.rollback()


def _ensure_lightweight_schema_updates(app):
    """Apply small additive schema updates for local/dev databases.

    Proper Alembic migrations should replace this before production rollout.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('users')}
    statements = []
    dialect = db.engine.dialect.name
    bool_false = 'false' if dialect == 'postgresql' else '0'

    if 'account_status' not in columns:
        statements.append("ALTER TABLE users ADD COLUMN account_status VARCHAR(16) NOT NULL DEFAULT 'active'")
    if 'profile_complete' not in columns:
        statements.append(f"ALTER TABLE users ADD COLUMN profile_complete BOOLEAN NOT NULL DEFAULT {bool_false}")
    if 'email' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN email VARCHAR(255)')
    if 'first_name' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN first_name VARCHAR(80)')
    if 'last_name' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN last_name VARCHAR(80)')
    if 'display_name' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN display_name VARCHAR(120)')
    if 'requested_team_id' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN requested_team_id INTEGER')
    if 'requested_member_role' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN requested_member_role VARCHAR(32)')
    if 'review_action' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN review_action VARCHAR(16)')
    if 'review_reason' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN review_reason TEXT')
    if 'reviewed_by_user_id' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN reviewed_by_user_id INTEGER')
    if 'reviewed_at' not in columns:
        statements.append('ALTER TABLE users ADD COLUMN reviewed_at TIMESTAMP')

    if 'team_memberships' in inspector.get_table_names():
        membership_columns = {column['name'] for column in inspector.get_columns('team_memberships')}
        if 'valid_from' not in membership_columns:
            statements.append('ALTER TABLE team_memberships ADD COLUMN valid_from DATE')
        if 'valid_to' not in membership_columns:
            statements.append('ALTER TABLE team_memberships ADD COLUMN valid_to DATE')

    if 'user_review_events' not in inspector.get_table_names():
        timestamp_type = 'TIMESTAMPTZ' if dialect == 'postgresql' else 'TIMESTAMP'
        statements.append(
            'CREATE TABLE IF NOT EXISTS user_review_events ('
            'id INTEGER PRIMARY KEY, '
            'user_id INTEGER NOT NULL, '
            'action VARCHAR(16) NOT NULL, '
            'reason TEXT NULL, '
            'source VARCHAR(32) NOT NULL DEFAULT \'manual\', '
            'reviewed_by_user_id INTEGER NULL, '
            f'created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP'
            ')'
        )
        statements.append('CREATE INDEX IF NOT EXISTS ix_user_review_events_user_id ON user_review_events (user_id)')
        statements.append('CREATE INDEX IF NOT EXISTS ix_user_review_events_created_at ON user_review_events (created_at)')

    # services table: internal_url column
    if 'services' in inspector.get_table_names():
        service_columns = {col['name'] for col in inspector.get_columns('services')}
        if 'internal_url' not in service_columns:
            statements.append('ALTER TABLE services ADD COLUMN internal_url VARCHAR(255)')

    for statement in statements:
        db.session.execute(text(statement))
    if statements:
        db.session.commit()
        app.logger.info('Applied lightweight auth schema updates.')
