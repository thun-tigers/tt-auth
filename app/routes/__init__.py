import functools
from flask import redirect, url_for, flash, request
from ..jwt_utils import get_jwt_from_request, validate_jwt


def login_required(f):
    """Decorator: requires a valid JWT cookie. Passes current_user payload as first kwarg."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = get_jwt_from_request()
        payload = validate_jwt(token) if token else None
        if not payload:
            next_path = request.full_path if request.query_string else request.path
            return redirect(url_for('auth.login', next=next_path))
        return f(*args, current_user=payload, **kwargs)
    return decorated


def admin_required(f):
    """Decorator: requires admin role. Must be applied after @login_required."""
    @functools.wraps(f)
    def decorated(*args, current_user=None, **kwargs):
        if not current_user or current_user.get('role') != 'admin':
            flash('Nur Administratoren haben Zugriff.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, current_user=current_user, **kwargs)
    return decorated
