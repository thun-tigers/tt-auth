from urllib.parse import urljoin, urlparse

from flask import Blueprint, render_template, redirect, url_for, request, flash, make_response
from ..extensions import db, limiter
from ..models import Service, ServiceAccess, Team, TeamMembership, User
from ..forms import LoginForm, RegisterForm
from ..jwt_utils import generate_jwt, set_jwt_cookie, clear_jwt_cookie, get_jwt_from_request, validate_jwt

bp = Blueprint('auth', __name__)


def is_safe_internal_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('20/minute', methods=['POST'])
def login():
    next_page = request.args.get('next', '').strip()
    if next_page and not is_safe_internal_url(next_page):
        next_page = ''

    # Already logged in → redirect to dashboard
    token = get_jwt_from_request()
    if token and validate_jwt(token):
        return redirect(next_page or url_for('dashboard.index'))

    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if not user.can_login:
                flash('Dein Konto ist noch nicht freigegeben oder wurde gesperrt.', 'warning')
                return render_template('login.html', form=form, next_page=next_page)
            token = generate_jwt(user)
            response = make_response(redirect(next_page or url_for('dashboard.index')))
            set_jwt_cookie(response, token)
            return response
        flash('Ungültiger Benutzername oder Passwort.', 'danger')

    return render_template('login.html', form=form, next_page=next_page)


@bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10/hour', methods=['POST'])
def register():
    form = RegisterForm(request.form)
    teams = Team.query.filter_by(is_active=True).order_by(Team.sort_order, Team.name).all()
    form.requested_team_id.choices = [(team.id, team.name) for team in teams]
    if request.method == 'GET':
        seniors = next((team for team in teams if team.code == 'SENIORS'), None)
        if seniors:
            form.requested_team_id.data = seniors.id
    if request.method == 'POST' and form.validate():
        username = form.username.data.strip()
        email = (form.email.data or '').strip().lower() or None
        if User.query.filter_by(username=username).first():
            flash(f'Der Benutzername "{username}" ist bereits vergeben.', 'danger')
        elif email and User.query.filter_by(email=email).first():
            flash('Diese E-Mail-Adresse wird bereits verwendet.', 'danger')
        else:
            first_name = form.first_name.data.strip()
            last_name = form.last_name.data.strip()
            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                display_name=f'{first_name} {last_name}',
                role='user',
                account_status='draft',
                is_active=True,
                profile_complete=False,
                requested_team_id=form.requested_team_id.data,
                requested_member_role=form.requested_member_role.data,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            default_services = Service.query.filter(
                Service.name.in_(['members', 'agenda', 'attendance']),
                Service.is_active.is_(True),
            ).all()
            for service in default_services:
                db.session.add(ServiceAccess(
                    user_id=user.id,
                    service_id=service.id,
                    role='user',
                    is_active=True,
                ))
            db.session.add(TeamMembership(
                user_id=user.id,
                team_id=form.requested_team_id.data,
                member_role=form.requested_member_role.data,
                is_active=False,
            ))
            db.session.commit()
            token = generate_jwt(user)
            response = make_response(redirect(url_for('dashboard.index', next_service='tt-members')))
            set_jwt_cookie(response, token)
            return response

    return render_template('register.html', form=form, teams=teams)


@bp.route('/logout')
def logout():
    response = make_response(redirect(url_for('auth.login')))
    clear_jwt_cookie(response)
    return response
