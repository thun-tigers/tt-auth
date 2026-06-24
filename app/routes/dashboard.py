from urllib.parse import urlencode
from flask import Blueprint, render_template, redirect, url_for, flash, request, make_response
from ..extensions import db
from ..models import Service, ServiceAccess, User
from . import login_required
from ..jwt_utils import generate_sso_token

bp = Blueprint('dashboard', __name__)


@bp.route('/health')
def health():
    return {'status': 'ok'}, 200


def get_service_audience(service):
    service_name = (service.name or '').strip().lower().replace(' ', '-')
    if service_name.startswith('tt-'):
        return service_name
    return f'tt-{service_name}'


@bp.route('/')
@login_required
def index(current_user):
    user = db.session.get(User, int(current_user['sub']))
    if not user or not user.can_login:
        flash('Dein Konto ist nicht aktiv.', 'warning')
        return redirect(url_for('auth.logout'))

    requested_service = (request.args.get('next_service') or '').strip().lower()
    requested_target = (request.args.get('next') or '').strip()
    service_access = (
        ServiceAccess.query
        .join(Service, Service.id == ServiceAccess.service_id)
        .filter(
            ServiceAccess.user_id == user.id,
            ServiceAccess.is_active.is_(True),
            Service.is_active.is_(True),
        )
        .order_by(Service.sort_order, Service.name)
        .all()
    )

    services = []
    for access in service_access:
        service = access.service
        launch_kwargs = {'service_id': service.id}
        if requested_target:
            launch_kwargs['next'] = requested_target
        service.launch_url = url_for('dashboard.launch_service', **launch_kwargs)
        service.assigned_role = access.role
        service.audience = get_service_audience(service)
        services.append(service)

    if user.account_status == 'draft' or not user.profile_complete:
        member_services = [service for service in services if service.audience == 'tt-members']
        if member_services:
            services = member_services
            flash('Bitte vervollstaendige zuerst dein Profil.', 'warning')

    if requested_service:
        matching_service = next((service for service in services if service.audience == requested_service), None)
        if matching_service:
            launch_kwargs = {'service_id': matching_service.id}
            if requested_target:
                launch_kwargs['next'] = requested_target
            return redirect(url_for('dashboard.launch_service', **launch_kwargs))

    return render_template('dashboard.html', services=services, current_user=current_user)


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile(current_user):
    user = db.session.get(User, int(current_user['sub']))
    if not user or not user.can_login:
        flash('Dein Konto ist nicht aktiv.', 'warning')
        return redirect(url_for('auth.logout'))

    access = (
        ServiceAccess.query
        .join(Service, Service.id == ServiceAccess.service_id)
        .filter(
            ServiceAccess.user_id == user.id,
            ServiceAccess.is_active.is_(True),
            Service.is_active.is_(True),
            Service.name == 'members',
        )
        .first()
    )
    members_profile_url = None
    if access:
        members_profile_url = url_for('dashboard.launch_service', service_id=access.service_id, next='/profile')

    selected_theme = (request.cookies.get('tt_theme') or 'system').strip().lower()
    if selected_theme not in {'light', 'dark', 'system'}:
        selected_theme = 'system'

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()

        if action == 'profile':
            first_name = (request.form.get('first_name') or '').strip() or None
            last_name = (request.form.get('last_name') or '').strip() or None
            display_name = (request.form.get('display_name') or '').strip() or None
            email = (request.form.get('email') or '').strip().lower() or None

            if email:
                email_owner = User.query.filter(User.email == email, User.id != user.id).first()
                if email_owner:
                    flash('Diese E-Mail-Adresse wird bereits verwendet.', 'danger')
                    return redirect(url_for('dashboard.profile'))

            user.first_name = first_name
            user.last_name = last_name
            user.display_name = display_name
            user.email = email
            db.session.commit()
            flash('Profildaten wurden aktualisiert.', 'success')
            return redirect(url_for('dashboard.profile'))

        if action == 'password':
            current_password = request.form.get('current_password') or ''
            new_password = request.form.get('new_password') or ''
            new_password_confirm = request.form.get('new_password_confirm') or ''

            if not user.check_password(current_password):
                flash('Aktuelles Passwort ist nicht korrekt.', 'danger')
                return redirect(url_for('dashboard.profile'))

            if len(new_password) < 8:
                flash('Das neue Passwort muss mindestens 8 Zeichen haben.', 'danger')
                return redirect(url_for('dashboard.profile'))

            if new_password != new_password_confirm:
                flash('Die neuen Passwörter stimmen nicht überein.', 'danger')
                return redirect(url_for('dashboard.profile'))

            user.set_password(new_password)
            db.session.commit()
            flash('Passwort wurde geändert.', 'success')
            return redirect(url_for('dashboard.profile'))

        if action == 'theme':
            preference = (request.form.get('theme_preference') or 'system').strip().lower()
            if preference not in {'light', 'dark', 'system'}:
                preference = 'system'

            response = make_response(redirect(url_for('dashboard.profile')))
            response.set_cookie('tt_theme', preference, max_age=31536000, samesite='Lax')
            flash('Designmodus wurde gespeichert.', 'success')
            return response

    return render_template(
        'profile.html',
        current_user=current_user,
        user=user,
        members_profile_url=members_profile_url,
        selected_theme=selected_theme,
    )


@bp.route('/launch/<int:service_id>')
@login_required
def launch_service(current_user, service_id):
    user = db.session.get(User, int(current_user['sub']))
    if not user or not user.can_login:
        flash('Dein Konto ist nicht aktiv.', 'warning')
        return redirect(url_for('auth.logout'))

    service = Service.query.filter_by(id=service_id, is_active=True).first()
    if not service:
        flash('Service nicht gefunden oder deaktiviert.', 'danger')
        return redirect(url_for('dashboard.index'))

    if user.account_status == 'draft' and get_service_audience(service) != 'tt-members':
        flash('Vor dem Antrag muss das Mitgliederprofil vervollstaendigt werden.', 'warning')
        return redirect(url_for('dashboard.index'))

    access = ServiceAccess.query.filter_by(
        user_id=user.id,
        service_id=service.id,
        is_active=True,
    ).first()
    if not access:
        flash('Sie haben keinen Zugriff auf diesen Service.', 'danger')
        return redirect(url_for('dashboard.index'))

    service_base = (service.url or '').rstrip('/')
    audience = get_service_audience(service)
    token = generate_sso_token(
        user,
        audience=audience,
        service_role=access.role,
        platform_role=user.role,
    )
    query_params = {'token': token}
    next_target = (request.args.get('next') or '').strip()
    if next_target:
        query_params['next'] = next_target
    query = urlencode(query_params)
    return redirect(f'{service_base}/auth/sso?{query}')
