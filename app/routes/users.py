from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
import logging
import requests as http_requests
from datetime import datetime, timezone
from ..extensions import db
from ..models import User, Service, ServiceAccess, Team, TeamMembership, UserReviewEvent
from ..forms import UserForm
from . import login_required, admin_required

logger = logging.getLogger(__name__)

bp = Blueprint('users', __name__, url_prefix='/users')


def _is_platform_admin(current_user):
    actor = db.session.get(User, int(current_user['sub']))
    return bool(actor and actor.role == 'admin')


@bp.route('/')
@login_required
@admin_required
def index(current_user):
    selected_team_id = request.args.get('team_id', type=int)
    teams = Team.query.filter_by(is_active=True).order_by(Team.sort_order, Team.name).all()

    query = User.query.filter(User.account_status != 'draft')
    if selected_team_id:
        query = query.filter(
            User.memberships.any(TeamMembership.team_id == selected_team_id)
        )

    users = query.order_by(User.username).all()

    review_summary = _build_review_summary(users)
    is_platform_admin = _is_platform_admin(current_user)

    return render_template(
        'users.html',
        users=users,
        teams=teams,
        selected_team_id=selected_team_id,
        current_user=current_user,
        review_summary=review_summary,
        is_platform_admin=is_platform_admin,
    )


@bp.route('/<int:user_id>/reviews', methods=['GET'])
@login_required
@admin_required
def review_history(current_user, user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('users.index'))

    events = (
        UserReviewEvent.query
        .filter_by(user_id=user.id)
        .order_by(UserReviewEvent.created_at.desc(), UserReviewEvent.id.desc())
        .all()
    )

    reviewer_ids = sorted({event.reviewed_by_user_id for event in events if event.reviewed_by_user_id})
    reviewers = {}
    if reviewer_ids:
        reviewers = {reviewer.id: reviewer for reviewer in User.query.filter(User.id.in_(reviewer_ids)).all()}

    return render_template(
        'user_reviews.html',
        current_user=current_user,
        user=user,
        events=events,
        reviewers=reviewers,
        is_platform_admin=_is_platform_admin(current_user),
    )


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new(current_user):
    form = UserForm(request.form)
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name).all()
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
                profile_complete=form.profile_complete.data,
                is_active=form.is_active.data,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            _sync_service_access(user, services, request.form)
            db.session.commit()
            flash(f'Benutzer "{user.username}" erstellt.', 'success')
            return redirect(url_for('users.index'))
    return render_template(
        'user_form.html',
        form=form,
        action='Erstellen',
        current_user=current_user,
        services=services,
        service_roles={},
        is_platform_admin=_is_platform_admin(current_user),
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
    form = UserForm(request.form, obj=user)
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
            user.profile_complete = form.profile_complete.data
            user.is_active = form.is_active.data
            if form.password.data:
                user.set_password(form.password.data)
            _sync_service_access(user, services, request.form)
            db.session.commit()
            flash(f'Benutzer "{user.username}" aktualisiert.', 'success')
            return redirect(url_for('users.index'))
    service_roles = {access.service_id: access.role for access in user.service_access if access.is_active}
    return render_template(
        'user_form.html',
        form=form,
        action='Bearbeiten',
        user=user,
        current_user=current_user,
        services=services,
        service_roles=service_roles,
        is_platform_admin=_is_platform_admin(current_user),
    )


@bp.route('/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve(current_user, user_id):
    approver = db.session.get(User, int(current_user['sub']))

    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('users.index'))

    if user.account_status != 'pending' or not user.profile_complete:
        flash('Der Antrag ist noch nicht vollständig eingereicht.', 'warning')
        return redirect(url_for('users.index'))

    user.account_status = 'active'
    user.is_active = True
    user.review_action = 'approved'
    user.review_reason = None
    user.reviewed_by_user_id = approver.id if approver else None
    user.reviewed_at = datetime.now(timezone.utc)
    _record_review_event(user, approver, 'approved', None, 'users_ui')
    _grant_default_service_access(user)
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
    is_platform_admin = (user.role or '').strip().lower() == 'admin'

    for service in services:
        field_name = f'service_role_{service.id}'
        if is_platform_admin:
            desired_role = 'admin'
        else:
            desired_role = (form_data.get(field_name) or 'none').strip().lower()
            if desired_role not in allowed_roles:
                desired_role = 'none'
            if service.name in {'members', 'agenda', 'attendance'} and desired_role == 'none':
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
        Service.name.in_(['members', 'agenda', 'attendance']),
        Service.is_active.is_(True),
    ).all()
    for service in services:
        access = ServiceAccess.query.filter_by(user_id=user.id, service_id=service.id).first()
        if access:
            access.role = access.role or 'user'
            access.is_active = True
            continue
        db.session.add(ServiceAccess(user_id=user.id, service_id=service.id, role='user', is_active=True))


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


def _record_review_event(user, approver, action, reason, source):
    db.session.add(UserReviewEvent(
        user_id=user.id,
        action=action,
        reason=reason,
        source=source,
        reviewed_by_user_id=approver.id if approver else None,
        created_at=datetime.now(timezone.utc),
    ))


def _build_review_summary(users):
    user_ids = [user.id for user in users]
    if not user_ids:
        return {}

    events = (
        UserReviewEvent.query
        .filter(UserReviewEvent.user_id.in_(user_ids))
        .order_by(UserReviewEvent.created_at.desc(), UserReviewEvent.id.desc())
        .all()
    )

    summary = {}
    for event in events:
        entry = summary.setdefault(event.user_id, {'count': 0, 'latest': None})
        entry['count'] += 1
        if entry['latest'] is None:
            entry['latest'] = event
    return summary
