from urllib.parse import urlencode
from flask import Blueprint, render_template, redirect, current_app, url_for
from ..models import Service
from . import login_required
from ..jwt_utils import generate_sso_token

bp = Blueprint('dashboard', __name__)


@bp.route('/')
@login_required
def index(current_user):
    services = (
        Service.query
        .filter_by(is_active=True)
        .filter(
            (Service.required_role == 'user') |
            (Service.required_role == current_user['role'])
        )
        .order_by(Service.sort_order, Service.name)
        .all()
    )

    for service in services:
        launch_url = service.url
        if (service.name or '').strip().lower() == 'agenda':
            launch_url = url_for('dashboard.launch_agenda')
        service.launch_url = launch_url

    return render_template('dashboard.html', services=services, current_user=current_user)


@bp.route('/launch/agenda')
@login_required
def launch_agenda(current_user):
    agenda_base = current_app.config.get('DEFAULT_AGENDA_URL', 'http://localhost:8085').rstrip('/')
    token = generate_sso_token(current_user, audience='tt-agenda')
    query = urlencode({'token': token})
    return redirect(f'{agenda_base}/auth/sso?{query}')
