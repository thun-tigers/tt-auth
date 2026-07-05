import jwt
from datetime import datetime, timedelta, timezone
from flask import current_app, request


def generate_jwt(user):
    """Generate a signed JWT for the given user."""
    now = datetime.now(timezone.utc)
    expiry_hours = current_app.config.get('JWT_EXPIRY_HOURS', 8)
    claims = user.auth_claims() if hasattr(user, 'auth_claims') else {}
    role_permissions = _build_role_permission_claims(claims.get('memberships') or [])
    permissions = _build_permissions(user.role, user.role, claims.get('memberships') or [], role_permissions)
    payload = {
        'sub': str(user.id),
        'username': user.username,
        'role': user.role,
        'account_status': user.account_status,
        'profile_complete': user.profile_complete,
        'memberships': claims.get('memberships') or [],
        'pending_memberships': claims.get('pending_memberships') or [],
        'teams': claims.get('teams') or [],
        'member_roles': claims.get('member_roles') or [],
        'role_permissions': role_permissions,
        'permissions': permissions,
        'iat': now,
        'exp': now + timedelta(hours=expiry_hours),
    }
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


def validate_jwt(token):
    """Validate a JWT and return the payload, or None on failure."""
    try:
        payload = jwt.decode(
            token,
            current_app.config['SECRET_KEY'],
            algorithms=['HS256'],
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_jwt_from_request():
    """Read the JWT from the request cookie."""
    cookie_name = current_app.config.get('JWT_COOKIE_NAME', 'tt_jwt')
    return request.cookies.get(cookie_name)


def set_jwt_cookie(response, token):
    """Attach the JWT as an HTTP-only cookie on the response."""
    cookie_name = current_app.config.get('JWT_COOKIE_NAME', 'tt_jwt')
    expiry_hours = current_app.config.get('JWT_EXPIRY_HOURS', 8)
    max_age = expiry_hours * 3600
    domain = current_app.config.get('JWT_COOKIE_DOMAIN')
    secure = current_app.config.get('JWT_COOKIE_SECURE', False)
    response.set_cookie(
        cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite='Lax',
        domain=domain,
    )
    return response


def clear_jwt_cookie(response):
    """Remove the JWT cookie from the response."""
    cookie_name = current_app.config.get('JWT_COOKIE_NAME', 'tt_jwt')
    domain = current_app.config.get('JWT_COOKIE_DOMAIN')
    secure = current_app.config.get('JWT_COOKIE_SECURE', False)

    # Remove host-only cookie variant first.
    response.delete_cookie(
        cookie_name,
        path='/',
        secure=secure,
        httponly=True,
        samesite='Lax',
    )

    domains = set()
    if domain:
        domains.add(domain)
        domains.add(domain.lstrip('.'))

    host = (request.host or '').split(':', 1)[0]
    if host:
        domains.add(host)

        host_parts = host.split('.')
        if len(host_parts) >= 2:
            domains.add('.' + '.'.join(host_parts[-2:]))

    for candidate in sorted(d for d in domains if d):
        response.delete_cookie(
            cookie_name,
            path='/',
            domain=candidate,
            secure=secure,
            httponly=True,
            samesite='Lax',
        )

    return response


def generate_sso_token(user, audience='tt-agenda', service_role=None, platform_role=None):
    """Generate a short-lived SSO token for trusted downstream services."""
    now = datetime.now(timezone.utc)
    ttl_seconds = current_app.config.get('SSO_TOKEN_EXPIRY_SECONDS', 60)
    resolved_service_role = (
        service_role
        or (user.get('role') if isinstance(user, dict) else user.role)
        or 'user'
    )
    resolved_platform_role = (
        platform_role
        or (user.get('role') if isinstance(user, dict) else user.role)
        or 'user'
    )
    claims = {}
    if not isinstance(user, dict) and hasattr(user, 'auth_claims'):
        claims = user.auth_claims()
    elif isinstance(user, dict):
        claims = {
            'profile_complete': user.get('profile_complete', False),
            'account_status': user.get('account_status'),
            'memberships': user.get('memberships', []),
            'pending_memberships': user.get('pending_memberships', []),
            'teams': user.get('teams', []),
            'member_roles': user.get('member_roles', []),
        }

    role_permissions = _build_role_permission_claims(claims.get('memberships') or [])
    permissions = _build_permissions(resolved_service_role, resolved_platform_role, claims.get('memberships') or [], role_permissions)

    payload = {
        'sub': str(user.get('sub') if isinstance(user, dict) else user.id),
        'username': user.get('username') if isinstance(user, dict) else user.username,
        'role': resolved_service_role,
        'service_role': resolved_service_role,
        'platform_role': resolved_platform_role,
        'profile_complete': bool(claims.get('profile_complete')),
        'account_status': claims.get('account_status') or 'active',
        'first_name': claims.get('first_name'),
        'last_name': claims.get('last_name'),
        'display_name': claims.get('display_name'),
        'email': claims.get('email'),
        'memberships': claims.get('memberships') or [],
        'pending_memberships': claims.get('pending_memberships') or [],
        'teams': claims.get('teams') or [],
        'member_roles': claims.get('member_roles') or [],
        'role_permissions': role_permissions,
        'permissions': permissions,
        'aud': audience,
        'iat': now,
        'exp': now + timedelta(seconds=ttl_seconds),
    }
    secret = current_app.config.get('SSO_SHARED_SECRET') or current_app.config['SECRET_KEY']
    return jwt.encode(payload, secret, algorithm='HS256')


def _build_permissions(service_role, platform_role, memberships, role_permissions=None):
    if platform_role == 'admin' or service_role == 'admin':
        return ['*']

    permissions = {'profile:read', 'profile:update'}
    role_permissions = role_permissions or {}

    for service_name, service_perms in role_permissions.items():
        for perm in service_perms:
            permissions.add(f'service:{service_name}:{perm}')

    for membership in memberships:
        team_code = membership.get('team_code')
        member_role = membership.get('member_role')
        if not team_code:
            continue
        permissions.add(f'team:{team_code}:read')
        if member_role in ('coach', 'head_coach'):
            permissions.add(f'team:{team_code}:write')
        if member_role == 'head_coach':
            permissions.add(f'team:{team_code}:admin')
    return sorted(permissions)


def _build_role_permission_claims(memberships):
    from .models import RolePermission

    member_roles = sorted({
        (membership.get('member_role') or '').strip().lower()
        for membership in memberships
        if membership.get('member_role')
    })
    if not member_roles:
        return {}

    rows = RolePermission.query.filter(
        RolePermission.is_active.is_(True),
        RolePermission.member_role_key.in_(member_roles),
    ).order_by(
        RolePermission.sort_order,
        RolePermission.service_name,
        RolePermission.permission_key,
    ).all()

    result = {}
    for row in rows:
        result.setdefault(row.service_name, [])
        if row.permission_key not in result[row.service_name]:
            result[row.service_name].append(row.permission_key)
    return result


def validate_sso_token(token, audience='tt-agenda'):
    """Validate an SSO token and return payload, or None on failure."""
    try:
        secret = current_app.config.get('SSO_SHARED_SECRET') or current_app.config['SECRET_KEY']
        return jwt.decode(token, secret, algorithms=['HS256'], audience=audience)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
