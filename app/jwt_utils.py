import jwt
from datetime import datetime, timedelta, timezone
from flask import current_app, request


def generate_jwt(user):
    """Generate a signed JWT for the given user."""
    now = datetime.now(timezone.utc)
    expiry_hours = current_app.config.get('JWT_EXPIRY_HOURS', 8)
    payload = {
        'sub': str(user.id),
        'username': user.username,
        'role': user.role,
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
    response.set_cookie(
        cookie_name,
        '',
        max_age=0,
        httponly=True,
        secure=secure,
        samesite='Lax',
        domain=domain,
    )
    return response


def generate_sso_token(user, audience='tt-agenda'):
    """Generate a short-lived SSO token for trusted downstream services."""
    now = datetime.now(timezone.utc)
    ttl_seconds = current_app.config.get('SSO_TOKEN_EXPIRY_SECONDS', 60)
    payload = {
        'sub': str(user.get('sub') if isinstance(user, dict) else user.id),
        'username': user.get('username') if isinstance(user, dict) else user.username,
        'role': user.get('role') if isinstance(user, dict) else user.role,
        'aud': audience,
        'iat': now,
        'exp': now + timedelta(seconds=ttl_seconds),
    }
    secret = current_app.config.get('SSO_SHARED_SECRET') or current_app.config['SECRET_KEY']
    return jwt.encode(payload, secret, algorithm='HS256')


def validate_sso_token(token, audience='tt-agenda'):
    """Validate an SSO token and return payload, or None on failure."""
    try:
        secret = current_app.config.get('SSO_SHARED_SECRET') or current_app.config['SECRET_KEY']
        return jwt.decode(token, secret, algorithms=['HS256'], audience=audience)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
