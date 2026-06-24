from flask import Blueprint, current_app, jsonify, request
from datetime import datetime, timezone

from ..extensions import db
from ..models import TeamMembership, User, UserReviewEvent

bp = Blueprint('api', __name__, url_prefix='/api')


def _authorized():
    expected = current_app.config.get('INTERNAL_API_SECRET')
    provided = request.headers.get('X-TT-Internal-Secret')
    return bool(expected and provided and provided == expected)


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
        if membership.is_active and membership.member_role in {'team_manager', 'head_coach'}
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
    services = ['members', 'agenda']
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
