from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
import logging
import requests as http_requests
from datetime import datetime, timezone
from ..extensions import db
from ..models import Team, TeamMembership, User, Service, ServiceAccess, UserReviewEvent
from ..forms import UserForm
from . import login_required, admin_required

logger = logging.getLogger(__name__)

bp = Blueprint('users', __name__, url_prefix='/users')


def _is_platform_admin(current_user):
    actor = db.session.get(User, int(current_user['sub']))
    return bool(actor and actor.role == 'admin')


def _managed_team_ids(current_user):
    actor = db.session.get(User, int(current_user['sub']))
    if not actor:
        return set()
    return {
        membership.team_id
        for membership in actor.memberships
        if membership.is_active and membership.member_role in {'team_manager', 'head_coach'}
    }


@bp.route('/')
@login_required
def index(current_user):
    is_platform_admin = _is_platform_admin(current_user)
    manager_team_ids = _managed_team_ids(current_user)

    if is_platform_admin:
        users = User.query.filter(User.account_status != 'draft').order_by(User.username).all()
    elif manager_team_ids:
        users = (
            User.query
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .filter(
                User.account_status == 'pending',
                User.profile_complete.is_(True),
                TeamMembership.is_active.is_(False),
                TeamMembership.team_id.in_(manager_team_ids),
            )
            .distinct()
            .order_by(User.username)
            .all()
        )
    else:
        flash('Nur Administratoren oder Team-Manager haben Zugriff.', 'danger')
        return redirect(url_for('dashboard.index'))

    review_summary = _build_review_summary(users)
    pending_summary = _build_pending_summary(users)
    approvable_user_ids = set()
    if is_platform_admin:
        approvable_user_ids = {user.id for user in users if user.account_status == 'pending'}
    else:
        for user in users:
            pending_items = pending_summary.get(user.id, [])
            if any(item.team_id in manager_team_ids for item in pending_items):
                approvable_user_ids.add(user.id)

    return render_template(
        'users.html',
        users=users,
        current_user=current_user,
        is_platform_admin=is_platform_admin,
        manager_team_ids=manager_team_ids,
        review_summary=review_summary,
        pending_summary=pending_summary,
        approvable_user_ids=approvable_user_ids,
    )


@bp.route('/<int:user_id>/reviews', methods=['GET'])
@login_required
def review_history(current_user, user_id):
    is_platform_admin = _is_platform_admin(current_user)
    manager_team_ids = _managed_team_ids(current_user)

    if not is_platform_admin and not manager_team_ids:
        flash('Nur Administratoren oder Team-Manager haben Zugriff.', 'danger')
        return redirect(url_for('dashboard.index'))

    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('users.index'))

    if not _can_access_user_review(user, is_platform_admin, manager_team_ids):
        flash('Keine Berechtigung für diese Review-Historie.', 'danger')
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
        is_platform_admin=is_platform_admin,
        manager_team_ids=manager_team_ids,
    )


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
                profile_complete=form.profile_complete.data,
                is_active=form.is_active.data,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            _sync_service_access(user, services, request.form)
            _sync_team_memberships(user, teams, request.form)
            _sync_pending_team_memberships(user, teams, request.form)
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
        pending_roles={},
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
            _sync_team_memberships(user, teams, request.form)
            _sync_pending_team_memberships(user, teams, request.form)
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
    pending_roles = {}
    for membership in user.memberships:
        if membership.is_active:
            continue
        pending_roles.setdefault(membership.team_id, set()).add(membership.member_role)
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
        pending_roles=pending_roles,
    )


@bp.route('/<int:user_id>/approve', methods=['POST'])
@login_required
def approve(current_user, user_id):
    approver = db.session.get(User, int(current_user['sub']))
    is_platform_admin = _is_platform_admin(current_user)
    manager_team_ids = _managed_team_ids(current_user)
    if not is_platform_admin and not manager_team_ids:
        flash('Nur Administratoren oder Team-Manager können freigeben.', 'danger')
        return redirect(url_for('dashboard.index'))

    user = db.session.get(User, user_id)
    if not user:
        flash('Benutzer nicht gefunden.', 'danger')
        return redirect(url_for('users.index'))

    if not is_platform_admin:
        if not _has_pending_membership_for_teams(user, manager_team_ids):
            flash('Du kannst nur Benutzer deines Teams freigeben.', 'danger')
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
    _activate_pending_memberships(user, None if is_platform_admin else manager_team_ids)
    _sync_requested_fields_from_pending(user)
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
    # Backward-compatible wrapper
    _activate_pending_memberships(user)
    _sync_requested_fields_from_pending(user)


def _sync_team_memberships(user, teams, form_data):
    allowed_roles = {'none', 'player', 'coach', 'head_coach', 'team_manager'}
    existing_active = {
        membership.team_id: membership
        for membership in user.memberships
        if membership.is_active
    }

    for team in teams:
        field_name = f'team_role_{team.id}'
        desired_role = (form_data.get(field_name) or 'none').strip().lower()
        if desired_role not in allowed_roles:
            desired_role = 'none'

        current_membership = existing_active.get(team.id)
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


def _sync_pending_team_memberships(user, teams, form_data):
    role_options = ('player', 'coach', 'head_coach', 'team_manager')
    active_keys = {
        (membership.team_id, membership.member_role)
        for membership in user.memberships
        if membership.is_active
    }
    existing_pending = {
        (membership.team_id, membership.member_role): membership
        for membership in user.memberships
        if not membership.is_active
    }

    selected = set()
    for team in teams:
        for role in role_options:
            field_name = f'pending_role_{team.id}_{role}'
            if form_data.get(field_name):
                selected.add((team.id, role))

    # Ignore pending choices that are already active memberships.
    selected -= active_keys

    for key, membership in list(existing_pending.items()):
        if key not in selected:
            db.session.delete(membership)

    for team_id, role in selected:
        if (team_id, role) in existing_pending:
            continue
        db.session.add(TeamMembership(
            user_id=user.id,
            team_id=team_id,
            member_role=role,
            is_active=False,
        ))

    _sync_requested_fields_from_pending(user)


def _sync_requested_fields_from_pending(user):
    pending = sorted(
        [
            (membership.team_id, membership.member_role)
            for membership in user.memberships
            if not membership.is_active
        ],
        key=lambda item: (item[0], item[1]),
    )
    if pending:
        user.requested_team_id = pending[0][0]
        user.requested_member_role = pending[0][1]
        return
    user.requested_team_id = None
    user.requested_member_role = None


def _activate_pending_memberships(user, allowed_team_ids=None):
    for membership in user.memberships:
        if membership.is_active:
            continue
        if allowed_team_ids is not None and membership.team_id not in allowed_team_ids:
            continue
        membership.is_active = True


def _has_pending_membership_for_teams(user, team_ids):
    for membership in user.memberships:
        if not membership.is_active and membership.team_id in team_ids:
            return True
    return False


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


def _can_access_user_review(user, is_platform_admin, manager_team_ids):
    if is_platform_admin:
        return True
    if user.requested_team_id and user.requested_team_id in manager_team_ids:
        return True
    for membership in user.memberships:
        if membership.team_id in manager_team_ids:
            return True
    return False


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


def _build_pending_summary(users):
    user_ids = [user.id for user in users]
    if not user_ids:
        return {}

    pending_memberships = (
        TeamMembership.query
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id.in_(user_ids),
            TeamMembership.is_active.is_(False),
        )
        .order_by(Team.sort_order, Team.name, TeamMembership.member_role)
        .all()
    )

    summary = {}
    for membership in pending_memberships:
        summary.setdefault(membership.user_id, []).append(membership)
    return summary
