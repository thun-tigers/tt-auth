from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
import logging
import requests as http_requests
from ..extensions import db
from ..models import Team, TeamMembership, User, Service, ServiceAccess
from ..forms import UserForm
from . import login_required, admin_required

logger = logging.getLogger(__name__)

bp = Blueprint('users', __name__, url_prefix='/users')


@bp.route('/')
@login_required
@admin_required
def index(current_user):
    users = User.query.filter(User.account_status != 'draft').order_by(User.username).all()
    return render_template('users.html', users=users, current_user=current_user)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new(current_user):
    form = UserForm(request.form)
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name).all()
    teams = Team.query.filter_by(is_active=True).order_by(Team.sort_order, Team.name).all()
    form.requested_team_id.choices = [(0, 'Keine')] + [(team.id, team.name) for team in teams]
    if request.method == 'POST' and form.validate():
        if User.query.filter_by(username=form.username.data).first():
            flash(f'Benutzername "{form.username.data}" ist bereits vergeben.', 'danger')
        elif form.email.data and User.query.filter_by(email=form.email.data.strip().lower()).first():
            flash('Diese E-Mail-Adresse wird bereits verwendet.', 'danger')
        elif not form.password.data:
            flash('Passwort ist erforderlich beim Erstellen eines Benutzers.', 'danger')
        else:
            first_name = (form.first_name.data or '').strip() or None
            last_name = (form.last_name.data or '').strip() or None
            user = User(
                username=form.username.data,
                email=(form.email.data or '').strip().lower() or None,
                first_name=first_name,
                last_name=last_name,
                display_name=' '.join(part for part in (first_name, last_name) if part) or None,
                role=form.role.data,
                account_status=form.account_status.data,
                requested_team_id=form.requested_team_id.data or None,
                requested_member_role=form.requested_member_role.data or None,
                profile_complete=form.profile_complete.data,
                is_active=form.is_active.data,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            _sync_service_access(user, services, request.form)
            _sync_team_memberships(user, teams, request.form)
            db.session.commit()
            flash(f'Benutzer "{user.username}" erstellt.', 'success')
            return redirect(url_for('users.index'))
    return render_template(
        'user_form.html',
        form=form,
        action='Erstellen',
        current_user=current_user,
        services=services,
        teams=teams,
        service_roles={},
        team_roles={},
    )


@bp.route('/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(current_user, user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('users.index'))
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name).all()
    teams = Team.query.filter_by(is_active=True).order_by(Team.sort_order, Team.name).all()
    form = UserForm(request.form, obj=user)
    form.requested_team_id.choices = [(0, 'Keine')] + [(team.id, team.name) for team in teams]
    if request.method == 'GET':
        form.requested_team_id.data = user.requested_team_id or 0
        form.requested_member_role.data = user.requested_member_role or ''
    if request.method == 'POST' and form.validate():
        existing = User.query.filter_by(username=form.username.data).first()
        existing_email = User.query.filter_by(email=(form.email.data or '').strip().lower()).first() if form.email.data else None
        if existing and existing.id != user.id:
            flash(f'Benutzername "{form.username.data}" ist bereits vergeben.', 'danger')
        elif existing_email and existing_email.id != user.id:
            flash('Diese E-Mail-Adresse wird bereits verwendet.', 'danger')
        else:
            user.username = form.username.data
            user.email = (form.email.data or '').strip().lower() or None
            user.first_name = (form.first_name.data or '').strip() or None
            user.last_name = (form.last_name.data or '').strip() or None
            user.display_name = ' '.join(part for part in (user.first_name, user.last_name) if part) or None
            user.role = form.role.data
            user.account_status = form.account_status.data
            user.requested_team_id = form.requested_team_id.data or None
            user.requested_member_role = form.requested_member_role.data or None
            user.profile_complete = form.profile_complete.data
            user.is_active = form.is_active.data
            if form.password.data:
                user.set_password(form.password.data)
            _sync_service_access(user, services, request.form)
            _sync_team_memberships(user, teams, request.form)
            db.session.flush()
            # Auto-approve: hat der Benutzer mindestens eine aktive Team-Mitgliedschaft,
            # werden is_active und profile_complete automatisch gesetzt.
            has_active_membership = any(m.is_active for m in user.memberships)
            if has_active_membership:
                user.is_active = True
                user.profile_complete = True
                if user.account_status in ('draft', 'pending'):
                    user.account_status = 'active'
            db.session.commit()
            flash(f'Benutzer "{user.username}" aktualisiert.', 'success')
            return redirect(url_for('users.index'))
    service_roles = {access.service_id: access.role for access in user.service_access if access.is_active}
    team_roles = {membership.team_id: membership.member_role for membership in user.memberships if membership.is_active}
    return render_template(
        'user_form.html',
        form=form,
        action='Bearbeiten',
        user=user,
        current_user=current_user,
        services=services,
        teams=teams,
        service_roles=service_roles,
        team_roles=team_roles,
    )


@bp.route('/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve(current_user, user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('users.index'))
    if user.account_status != 'pending' or not user.profile_complete:
        flash('Der Antrag ist noch nicht vollständig eingereicht.', 'warning')
        return redirect(url_for('users.index'))

    user.account_status = 'active'
    user.is_active = True
    _grant_default_service_access(user)
    _apply_requested_membership(user)
    db.session.commit()
    flash(f'Benutzer "{user.username}" freigegeben.', 'success')
    return redirect(url_for('users.index'))


@bp.route('/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(current_user, user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
    elif str(user_id) == current_user['sub']:
        flash('Du kannst deinen eigenen Account nicht löschen.', 'danger')
    else:
        auth_user_id = user.id
        username = user.username
        db.session.delete(user)
        db.session.commit()
        _cascade_delete_user(auth_user_id, username)
        flash(f'Benutzer "{username}" gelöscht.', 'success')
    return redirect(url_for('users.index'))


def _sync_service_access(user, services, form_data):
    allowed_roles = {'none', 'user', 'admin'}
    existing = {access.service_id: access for access in user.service_access}

    for service in services:
        field_name = f'service_role_{service.id}'
        desired_role = (form_data.get(field_name) or 'none').strip().lower()
        if desired_role not in allowed_roles:
            desired_role = 'none'
        if service.name in {'members', 'agenda'} and desired_role == 'none':
            desired_role = 'user'

        current_access = existing.get(service.id)
        if desired_role == 'none':
            if current_access:
                db.session.delete(current_access)
            continue

        if current_access:
            current_access.role = desired_role
            current_access.is_active = True
        else:
            db.session.add(ServiceAccess(
                user_id=user.id,
                service_id=service.id,
                role=desired_role,
                is_active=True,
            ))


def _grant_default_service_access(user):
    services = Service.query.filter(
        Service.name.in_(['members', 'agenda']),
        Service.is_active.is_(True),
    ).all()
    for service in services:
        access = ServiceAccess.query.filter_by(user_id=user.id, service_id=service.id).first()
        if access:
            access.role = access.role or 'user'
            access.is_active = True
            continue
        db.session.add(ServiceAccess(user_id=user.id, service_id=service.id, role='user', is_active=True))


def _apply_requested_membership(user):
    if not user.requested_team_id or not user.requested_member_role:
        return
    if user.requested_member_role not in {'player', 'coach', 'head_coach'}:
        return
    membership = TeamMembership.query.filter_by(
        user_id=user.id,
        team_id=user.requested_team_id,
        member_role=user.requested_member_role,
    ).first()
    if membership:
        membership.is_active = True
        return
    db.session.add(TeamMembership(
        user_id=user.id,
        team_id=user.requested_team_id,
        member_role=user.requested_member_role,
        is_active=True,
    ))


def _sync_team_memberships(user, teams, form_data):
    allowed_roles = {'none', 'player', 'coach', 'head_coach'}
    existing = {membership.team_id: membership for membership in user.memberships}

    for team in teams:
        field_name = f'team_role_{team.id}'
        desired_role = (form_data.get(field_name) or 'none').strip().lower()
        if desired_role not in allowed_roles:
            desired_role = 'none'

        current_membership = existing.get(team.id)
        if desired_role == 'none':
            if current_membership:
                db.session.delete(current_membership)
            continue

        if current_membership:
            current_membership.member_role = desired_role
            current_membership.is_active = True
        else:
            db.session.add(TeamMembership(
                user_id=user.id,
                team_id=team.id,
                member_role=desired_role,
                is_active=True,
            ))


def _cascade_delete_user(auth_user_id: int, username: str) -> None:
    """Benachrichtigt alle Services per interner API über die Löschung eines Benutzers.

    Best-effort: Fehler blockieren den Delete nicht, werden aber geloggt.
    """
    secret = current_app.config.get('INTERNAL_API_SECRET')
    if not secret:
        logger.warning('INTERNAL_API_SECRET nicht konfiguriert – Cascade-Delete übersprungen.')
        return

    services = Service.query.filter(
        Service.internal_url.isnot(None),
        Service.is_active.is_(True),
    ).all()

    for service in services:
        url = f"{service.internal_url.rstrip('/')}/api/internal/users/{auth_user_id}"
        try:
            response = http_requests.delete(
                url,
                headers={'X-TT-Internal-Secret': secret},
                timeout=5,
            )
            if response.status_code == 404:
                logger.info('Cascade-Delete %s: Benutzer "%s" war nicht vorhanden.', service.name, username)
            elif response.status_code >= 400:
                logger.warning('Cascade-Delete %s: HTTP %s – %s', service.name, response.status_code, response.text)
            else:
                logger.info('Cascade-Delete %s: Benutzer "%s" erfolgreich entfernt.', service.name, username)
        except http_requests.RequestException as exc:
            logger.warning('Cascade-Delete %s: Verbindungsfehler – %s', service.name, exc)
