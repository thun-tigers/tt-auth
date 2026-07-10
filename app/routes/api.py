from flask import Blueprint, current_app, jsonify, request
from datetime import datetime, timezone

from ..extensions import db
from ..models import MemberRole, Service, ServiceAccess, Team, TeamMembership, User, UserReviewEvent

bp = Blueprint('api', __name__, url_prefix='/api')


def _authorized():
    expected = current_app.config.get('INTERNAL_API_SECRET')
    provided = request.headers.get('X-TT-Internal-Secret')
    return bool(expected and provided and provided == expected)


@bp.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'not_found'}), 404

    return jsonify({
        'id': user.id,
        'username': user.username,
        'display_name': user.full_name,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'role': user.role,
        'account_status': user.account_status,
        'profile_complete': user.profile_complete,
        'memberships': [membership.claim() for membership in user.memberships if membership.is_active],
        'teams': sorted({
            membership.team.code
            for membership in user.memberships
            if membership.is_active and membership.team and membership.team.code
        }),
    })


@bp.route('/users/<int:user_id>/profile-complete', methods=['POST'])
def mark_profile_complete(user_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'not_found'}), 404

    user.profile_complete = True
    if user.account_status == 'draft':
        user.account_status = 'pending'
    db.session.commit()
    return jsonify({
        'status': 'ok',
        'user_id': user.id,
        'profile_complete': user.profile_complete,
        'account_status': user.account_status,
    })


@bp.route('/users/<int:user_id>/profile', methods=['POST'])
def update_user_profile(user_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'not_found'}), 404

    first_name = (payload.get('first_name') or '').strip() or None
    last_name = (payload.get('last_name') or '').strip() or None
    display_name = (payload.get('display_name') or '').strip() or None
    email = (payload.get('email') or '').strip().lower() or None

    if email:
        email_owner = User.query.filter(User.email == email, User.id != user.id).first()
        if email_owner:
            return jsonify({'error': 'email_in_use'}), 409

    user.first_name = first_name
    user.last_name = last_name
    user.display_name = display_name or ' '.join(part for part in (first_name, last_name) if part) or None
    user.email = email
    db.session.commit()

    return jsonify({
        'status': 'ok',
        'user_id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'display_name': user.display_name,
        'email': user.email,
    })


def _can_manage_team(approver, team_id):
    if not approver or not team_id:
        return False
    if approver.role == 'admin':
        return True
    return bool(TeamMembership.query.filter_by(
        user_id=approver.id,
        team_id=team_id,
        is_active=True,
    ).filter(TeamMembership.member_role.in_(['team_manager', 'head_coach'])).first())


def _managed_team_ids(approver):
    if not approver:
        return set()
    return {
        membership.team_id
        for membership in approver.memberships
        if membership.is_active and membership.member_role in {'team_manager', 'team_betreuer', 'head_coach'}
    }


def _viewer_team_ids(approver):
    if not approver:
        return set()
    return {
        membership.team_id
        for membership in approver.memberships
        if membership.is_active and membership.member_role in {'coach', 'team_manager', 'team_betreuer', 'head_coach'}
    }


def _pending_memberships_for_user(user, allowed_team_ids=None):
    memberships = [membership for membership in user.memberships if not membership.is_active]
    if allowed_team_ids is None:
        return memberships
    return [membership for membership in memberships if membership.team_id in allowed_team_ids]


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


def _serialize_team(team):
    return {
        'id': team.id,
        'code': team.code,
        'name': team.name,
        'sort_order': team.sort_order,
    }


def _serialize_membership(membership):
    return {
        'id': membership.id,
        'team': _serialize_team(membership.team) if membership.team else {
            'id': membership.team_id,
            'code': None,
            'name': None,
            'sort_order': None,
        },
        'member_role': membership.member_role,
        'is_active': membership.is_active,
    }


def _serialize_team_roles(memberships):
    team_roles = {}
    for membership in sorted(
        memberships,
        key=lambda item: (item.team_id, item.member_role),
    ):
        team_roles.setdefault(membership.team_id, [])
        if membership.member_role not in team_roles[membership.team_id]:
            team_roles[membership.team_id].append(membership.member_role)
    return team_roles


def _managed_team_memberships_query(approver, allowed_team_ids):
    query = (
        User.query
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .filter(
            User.account_status == 'active',
            TeamMembership.is_active.is_(True),
        )
    )
    if allowed_team_ids is not None:
        query = query.filter(TeamMembership.team_id.in_(allowed_team_ids))
    return query


def _target_memberships_for_scope(target, allowed_team_ids=None, active_only=False):
    memberships = list(target.memberships)
    if allowed_team_ids is not None:
        memberships = [membership for membership in memberships if membership.team_id in allowed_team_ids]
    if active_only:
        memberships = [membership for membership in memberships if membership.is_active]
    return memberships


def _serialize_user_for_management(user, allowed_team_ids=None):
    memberships = _target_memberships_for_scope(user, allowed_team_ids)
    active_memberships = [membership for membership in memberships if membership.is_active]
    pending_memberships = [membership for membership in memberships if not membership.is_active]
    return {
        'id': user.id,
        'username': user.username,
        'display_name': user.display_name,
        'email': user.email,
        'account_status': user.account_status,
        'profile_complete': user.profile_complete,
        'platform_role': user.role,
        'service_role': user.role,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'active_memberships': [_serialize_membership(membership) for membership in active_memberships],
        'pending_memberships': [_serialize_membership(membership) for membership in pending_memberships],
        'team_roles': _serialize_team_roles(active_memberships),
    }


def _editor_allowed_team_ids(approver):
    if approver.role == 'admin':
        return None
    return _managed_team_ids(approver)


def _viewer_allowed_team_ids(approver):
    if approver.role == 'admin':
        return None
    return _viewer_team_ids(approver)


def _can_edit_user(approver, target, allowed_team_ids):
    if approver.role == 'admin':
        return True
    if not allowed_team_ids:
        return False
    return any(
        membership.team_id in allowed_team_ids
        for membership in target.memberships
        if membership.is_active or not membership.is_active
    )


def _can_view_user(approver, target, allowed_team_ids):
    if approver.role == 'admin':
        return True
    if not allowed_team_ids:
        return False
    return any(
        membership.team_id in allowed_team_ids
        for membership in target.memberships
        if membership.is_active or not membership.is_active
    )


def _validate_active_memberships_payload(payload):
    allowed_member_roles = {
        role.key
        for role in MemberRole.query.filter_by(is_active=True).all()
    }
    if not allowed_member_roles:
        allowed_member_roles = {'player', 'coach', 'head_coach', 'team_manager', 'team_betreuer'}

    raw = payload.get('active_memberships')
    if raw is None:
        return None, 'active_memberships_required'
    if not isinstance(raw, list):
        return None, 'active_memberships_must_be_list'

    selected = {}
    for entry in raw:
        if not isinstance(entry, dict):
            return None, 'active_memberships_invalid'
        team_id = entry.get('team_id')
        member_role = (entry.get('member_role') or 'none').strip().lower()
        if not isinstance(team_id, int):
            return None, 'active_memberships_invalid_team_id'
        if member_role != 'none' and member_role not in allowed_member_roles:
            return None, 'active_memberships_invalid_role'
        if member_role == 'none':
            continue
        selected.setdefault(team_id, [])
        if member_role not in selected[team_id]:
            selected[team_id].append(member_role)

    return selected, None


@bp.route('/team-manager/members', methods=['GET'])
def team_manager_members():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    approver_auth_user_id = request.args.get('approver_auth_user_id', type=int)
    if not approver_auth_user_id:
        return jsonify({'error': 'approver_auth_user_id_required'}), 400

    approver = db.session.get(User, approver_auth_user_id)
    if not approver:
        return jsonify({'error': 'approver_not_found'}), 404

    allowed_team_ids = _viewer_allowed_team_ids(approver)
    if approver.role != 'admin' and not allowed_team_ids:
        return jsonify({'error': 'forbidden'}), 403

    editor_allowed_team_ids = _editor_allowed_team_ids(approver)

    query_text = (request.args.get('q') or '').strip().lower()
    query = (
        User.query
        .filter(User.account_status == 'active')
        .order_by(User.display_name.is_(None), User.display_name, User.username)
    )

    if approver.role != 'admin':
        query = _managed_team_memberships_query(approver, allowed_team_ids)

    users = []
    seen_user_ids = set()
    for user in query.all():
        if user.id in seen_user_ids:
            continue
        seen_user_ids.add(user.id)
        users.append(user)
    if query_text:
        users = [
            user for user in users
            if query_text in (user.username or '').lower()
            or query_text in (user.display_name or '').lower()
            or query_text in (user.email or '').lower()
        ]

    teams = Team.query.filter_by(is_active=True).order_by(Team.sort_order, Team.name).all()
    if allowed_team_ids is not None:
        teams = [team for team in teams if team.id in allowed_team_ids]

    return jsonify({
        'status': 'ok',
        'is_platform_admin': approver.role == 'admin',
        'can_edit_members': approver.role == 'admin' or bool(editor_allowed_team_ids),
        'teams': [_serialize_team(team) for team in teams],
        'users': [
            {
                **_serialize_user_for_management(user, allowed_team_ids),
                'can_edit': _can_edit_user(approver, user, editor_allowed_team_ids),
            }
            for user in users
        ],
    })


@bp.route('/team-manager/members/<int:target_user_id>', methods=['GET'])
def team_manager_member_detail(target_user_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    approver_auth_user_id = request.args.get('approver_auth_user_id', type=int)
    if not approver_auth_user_id:
        return jsonify({'error': 'approver_auth_user_id_required'}), 400

    approver = db.session.get(User, approver_auth_user_id)
    target = db.session.get(User, target_user_id)
    if not approver:
        return jsonify({'error': 'approver_not_found'}), 404
    if not target:
        return jsonify({'error': 'target_user_not_found'}), 404

    allowed_team_ids = _viewer_allowed_team_ids(approver)
    if approver.role != 'admin' and not _can_view_user(approver, target, allowed_team_ids):
        return jsonify({'error': 'forbidden'}), 403

    editor_allowed_team_ids = _editor_allowed_team_ids(approver)

    teams = Team.query.filter_by(is_active=True).order_by(Team.sort_order, Team.name).all()
    if allowed_team_ids is not None:
        teams = [team for team in teams if team.id in allowed_team_ids]

    return jsonify({
        'status': 'ok',
        'is_platform_admin': approver.role == 'admin',
        'can_edit_member': _can_edit_user(approver, target, editor_allowed_team_ids),
        'teams': [_serialize_team(team) for team in teams],
        'user': {
            **_serialize_user_for_management(target, allowed_team_ids),
            'can_edit': _can_edit_user(approver, target, editor_allowed_team_ids),
        },
    })


@bp.route('/team-manager/members/<int:target_user_id>', methods=['POST'])
def team_manager_update_member(target_user_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    approver_auth_user_id = payload.get('approver_auth_user_id')
    if not approver_auth_user_id:
        return jsonify({'error': 'approver_auth_user_id_required'}), 400

    approver = db.session.get(User, int(approver_auth_user_id))
    target = db.session.get(User, target_user_id)
    if not approver:
        return jsonify({'error': 'approver_not_found'}), 404
    if not target:
        return jsonify({'error': 'target_user_not_found'}), 404

    allowed_team_ids = _editor_allowed_team_ids(approver)
    if approver.role != 'admin' and not _can_edit_user(approver, target, allowed_team_ids):
        return jsonify({'error': 'forbidden'}), 403

    selected, error = _validate_active_memberships_payload(payload)
    if error:
        return jsonify({'error': error}), 400

    if allowed_team_ids is not None:
        invalid_team_ids = [team_id for team_id in selected.keys() if team_id not in allowed_team_ids]
        if invalid_team_ids:
            return jsonify({'error': 'forbidden_team_scope'}), 403
    else:
        valid_team_ids = {team.id for team in Team.query.filter_by(is_active=True).all()}
        invalid_team_ids = [team_id for team_id in selected.keys() if team_id not in valid_team_ids]
        if invalid_team_ids:
            return jsonify({'error': 'invalid_team_id'}), 400

    desired_by_team = {team_id: list(roles) for team_id, roles in selected.items()}
    current_active = [membership for membership in target.memberships if membership.is_active]

    for membership in list(current_active):
        if allowed_team_ids is not None and membership.team_id not in allowed_team_ids:
            continue
        db.session.delete(membership)

    db.session.flush()

    for team_id, roles in desired_by_team.items():
        for role in roles:
            db.session.add(TeamMembership(
                user_id=target.id,
                team_id=team_id,
                member_role=role,
                is_active=True,
            ))

    _sync_requested_fields_from_pending(target)
    db.session.commit()

    return jsonify({
        'status': 'ok',
        'target_user_id': target.id,
        'user': _serialize_user_for_management(target, allowed_team_ids),
    })


@bp.route('/team-manager/pending-users', methods=['GET'])
def team_manager_pending_users():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    approver_auth_user_id = request.args.get('approver_auth_user_id', type=int)
    if not approver_auth_user_id:
        return jsonify({'error': 'approver_auth_user_id_required'}), 400

    approver = db.session.get(User, approver_auth_user_id)
    if not approver:
        return jsonify({'error': 'approver_not_found'}), 404

    manager_team_ids = _managed_team_ids(approver)

    if approver.role != 'admin' and not manager_team_ids:
        return jsonify({'error': 'forbidden'}), 403

    query = (
        User.query
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .filter(
            User.account_status == 'pending',
            User.profile_complete.is_(True),
            TeamMembership.is_active.is_(False),
        )
    )
    if approver.role != 'admin':
        query = query.filter(TeamMembership.team_id.in_(manager_team_ids))

    pending_users = query.distinct().order_by(User.created_at.asc()).all()
    return jsonify({
        'status': 'ok',
        'pending_users': [
            {
                **({
                    'requested_memberships': [
                        {
                            'team': {
                                'id': membership.team.id if membership.team else membership.team_id,
                                'name': membership.team.name if membership.team else None,
                                'code': membership.team.code if membership.team else None,
                            },
                            'member_role': membership.member_role,
                        }
                        for membership in _pending_memberships_for_user(
                            user,
                            None if approver.role == 'admin' else manager_team_ids,
                        )
                    ],
                }),
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'email': user.email,
                'requested_team_id': user.requested_team_id,
                'requested_team_code': user.requested_team.code if user.requested_team else None,
                'requested_team_name': user.requested_team.name if user.requested_team else None,
                'requested_member_role': user.requested_member_role,
                'created_at': user.created_at.isoformat() if user.created_at else None,
            }
            for user in pending_users
        ],
    })


@bp.route('/team-manager/approve-user', methods=['POST'])
def team_manager_approve_user():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    approver_auth_user_id = payload.get('approver_auth_user_id')
    target_user_id = payload.get('target_user_id')

    if not approver_auth_user_id or not target_user_id:
        return jsonify({'error': 'approver_auth_user_id_and_target_user_id_required'}), 400

    approver = db.session.get(User, int(approver_auth_user_id))
    target = db.session.get(User, int(target_user_id))
    if not approver:
        return jsonify({'error': 'approver_not_found'}), 404
    if not target:
        return jsonify({'error': 'target_user_not_found'}), 404

    managed_team_ids = _managed_team_ids(approver)
    pending_memberships = _pending_memberships_for_user(
        target,
        None if approver.role == 'admin' else managed_team_ids,
    )

    if approver.role != 'admin' and not pending_memberships:
        return jsonify({'error': 'forbidden'}), 403

    if target.account_status != 'pending' or not target.profile_complete:
        return jsonify({'error': 'invalid_target_status'}), 409

    target.account_status = 'active'
    target.is_active = True
    target.review_action = 'approved'
    target.review_reason = None
    target.reviewed_by_user_id = approver.id
    target.reviewed_at = datetime.now(timezone.utc)
    db.session.add(UserReviewEvent(
        user_id=target.id,
        action='approved',
        reason=None,
        source='team_manager_api',
        reviewed_by_user_id=approver.id,
        created_at=datetime.now(timezone.utc),
    ))

    # Minimal activation equivalent to users.approve route
    services = ['members', 'agenda', 'attendance']
    from ..models import Service, ServiceAccess
    for service in Service.query.filter(Service.name.in_(services), Service.is_active.is_(True)).all():
        access = ServiceAccess.query.filter_by(user_id=target.id, service_id=service.id).first()
        if access:
            access.role = access.role or 'user'
            access.is_active = True
        else:
            db.session.add(ServiceAccess(user_id=target.id, service_id=service.id, role='user', is_active=True))

    for membership in pending_memberships:
        membership.is_active = True

    _sync_requested_fields_from_pending(target)

    db.session.commit()
    return jsonify({'status': 'ok', 'target_user_id': target.id})


@bp.route('/team-manager/reject-user', methods=['POST'])
def team_manager_reject_user():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    approver_auth_user_id = payload.get('approver_auth_user_id')
    target_user_id = payload.get('target_user_id')
    reason = (payload.get('reason') or '').strip()

    if not approver_auth_user_id or not target_user_id:
        return jsonify({'error': 'approver_auth_user_id_and_target_user_id_required'}), 400

    approver = db.session.get(User, int(approver_auth_user_id))
    target = db.session.get(User, int(target_user_id))
    if not approver:
        return jsonify({'error': 'approver_not_found'}), 404
    if not target:
        return jsonify({'error': 'target_user_not_found'}), 404

    managed_team_ids = _managed_team_ids(approver)
    pending_memberships = _pending_memberships_for_user(
        target,
        None if approver.role == 'admin' else managed_team_ids,
    )

    if approver.role != 'admin' and not pending_memberships:
        return jsonify({'error': 'forbidden'}), 403

    if target.account_status != 'pending':
        return jsonify({'error': 'invalid_target_status'}), 409

    target.account_status = 'suspended'
    target.is_active = False
    target.review_action = 'rejected'
    target.review_reason = reason or None
    target.reviewed_by_user_id = approver.id
    target.reviewed_at = datetime.now(timezone.utc)
    db.session.add(UserReviewEvent(
        user_id=target.id,
        action='rejected',
        reason=reason or None,
        source='team_manager_api',
        reviewed_by_user_id=approver.id,
        created_at=datetime.now(timezone.utc),
    ))

    for membership in pending_memberships:
        membership.is_active = False

    _sync_requested_fields_from_pending(target)

    db.session.commit()

    if reason:
        current_app.logger.info(
            'Team-manager rejection: approver=%s target=%s team_id=%s reason=%s',
            approver.id,
            target.id,
            target.requested_team_id,
            reason,
        )

    return jsonify({'status': 'ok', 'target_user_id': target.id})


# ── Internal Services API (consumed by tt-infra) ───────────────────────────

def _serialize_service(service):
    return {
        'id': service.id,
        'name': service.name,
        'url': service.url,
        'internal_url': service.internal_url,
        'icon': service.icon,
        'description': service.description,
        'required_role': service.required_role,
        'is_active': service.is_active,
        'sort_order': service.sort_order,
    }


@bp.route('/internal/services', methods=['GET'])
def internal_services_list():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    services = Service.query.order_by(Service.sort_order, Service.name).all()
    return jsonify({'services': [_serialize_service(s) for s in services]})


@bp.route('/internal/services', methods=['POST'])
def internal_services_create():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    url_val = (payload.get('url') or '').strip()
    if not name or not url_val:
        return jsonify({'error': 'name_and_url_required'}), 400
    if Service.query.filter_by(name=name).first():
        return jsonify({'error': 'already_exists'}), 409
    service = Service(
        name=name,
        url=url_val,
        internal_url=(payload.get('internal_url') or '').strip() or None,
        icon=payload.get('icon') or 'grid',
        description=payload.get('description') or '',
        required_role=payload.get('required_role') or 'user',
        is_active=bool(payload.get('is_active', True)),
        sort_order=int(payload.get('sort_order') or 0),
    )
    db.session.add(service)
    db.session.commit()
    return jsonify({'status': 'created', 'service': _serialize_service(service)}), 201


@bp.route('/internal/services/<int:service_id>', methods=['GET'])
def internal_service_get(service_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    service = db.session.get(Service, service_id)
    if not service:
        return jsonify({'error': 'not_found'}), 404
    return jsonify({'service': _serialize_service(service)})


@bp.route('/internal/services/<int:service_id>', methods=['PUT'])
def internal_service_update(service_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    service = db.session.get(Service, service_id)
    if not service:
        return jsonify({'error': 'not_found'}), 404
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    url_val = (payload.get('url') or '').strip()
    if not name or not url_val:
        return jsonify({'error': 'name_and_url_required'}), 400
    existing = Service.query.filter_by(name=name).first()
    if existing and existing.id != service.id:
        return jsonify({'error': 'name_already_exists'}), 409
    service.name = name
    service.url = url_val
    service.internal_url = (payload.get('internal_url') or '').strip() or None
    service.icon = payload.get('icon') or 'grid'
    service.description = payload.get('description') or ''
    service.required_role = payload.get('required_role') or 'user'
    service.is_active = bool(payload.get('is_active', True))
    service.sort_order = int(payload.get('sort_order') or 0)
    db.session.commit()
    return jsonify({'status': 'updated', 'service': _serialize_service(service)})


@bp.route('/internal/services/<int:service_id>', methods=['DELETE'])
def internal_service_delete(service_id):
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401
    service = db.session.get(Service, service_id)
    if not service:
        return jsonify({'error': 'not_found'}), 404
    db.session.delete(service)
    db.session.commit()
    return jsonify({'status': 'deleted'})
