from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import MemberRole, RolePermission, Service, TeamMembership
from . import admin_required, login_required

bp = Blueprint('master_data', __name__, url_prefix='/master-data')

CRUD_PERMISSIONS = ('create', 'read', 'update', 'delete')


@bp.route('/member-roles', methods=['GET'])
@login_required
@admin_required
def member_roles(current_user):
    roles = MemberRole.query.order_by(MemberRole.sort_order, MemberRole.label).all()
    return render_template('master_data_member_roles.html', current_user=current_user, roles=roles)


@bp.route('/member-roles/new', methods=['POST'])
@login_required
@admin_required
def member_roles_new(current_user):
    key = (request.form.get('key') or '').strip().lower()
    label = (request.form.get('label') or '').strip()
    sort_order = request.form.get('sort_order', type=int)
    is_active = request.form.get('is_active') == 'y'

    if not key or not label:
        flash('Schlüssel und Bezeichnung sind erforderlich.', 'danger')
        return redirect(url_for('master_data.member_roles'))

    existing = MemberRole.query.filter_by(key=key).first()
    if existing:
        flash('Der Schlüssel existiert bereits.', 'danger')
        return redirect(url_for('master_data.member_roles'))

    if sort_order is None:
        sort_order = (MemberRole.query.count() + 1) * 10

    db.session.add(MemberRole(key=key, label=label, sort_order=sort_order, is_active=is_active))
    db.session.commit()
    flash('Mitgliedsrolle gespeichert.', 'success')
    return redirect(url_for('master_data.member_roles'))


@bp.route('/member-roles/<int:role_id>/edit', methods=['POST'])
@login_required
@admin_required
def member_roles_edit(current_user, role_id):
    role = db.session.get(MemberRole, role_id)
    if not role:
        flash('Mitgliedsrolle nicht gefunden.', 'danger')
        return redirect(url_for('master_data.member_roles'))

    role.label = (request.form.get('label') or '').strip() or role.label
    role.sort_order = request.form.get('sort_order', type=int) or role.sort_order
    role.is_active = request.form.get('is_active') == 'y'
    db.session.commit()
    flash('Mitgliedsrolle gespeichert.', 'success')
    return redirect(url_for('master_data.member_roles'))


@bp.route('/member-roles/<int:role_id>/delete', methods=['POST'])
@login_required
@admin_required
def member_roles_delete(current_user, role_id):
    role = db.session.get(MemberRole, role_id)
    if not role:
        flash('Mitgliedsrolle nicht gefunden.', 'danger')
        return redirect(url_for('master_data.member_roles'))

    in_use = TeamMembership.query.filter_by(member_role=role.key).first() is not None
    if in_use and role.key in {'player', 'coach', 'head_coach', 'team_manager', 'team_betreuer'}:
        flash('Standardrollen können nicht gelöscht werden.', 'warning')
        return redirect(url_for('master_data.member_roles'))

    db.session.delete(role)
    db.session.commit()
    flash('Mitgliedsrolle gelöscht.', 'success')
    return redirect(url_for('master_data.member_roles'))


@bp.route('/member-roles/reorder', methods=['POST'])
@login_required
@admin_required
def member_roles_reorder(current_user):
    ordered_ids = request.form.getlist('order')
    if not ordered_ids:
        flash('Keine Reihenfolge übermittelt.', 'danger')
        return redirect(url_for('master_data.member_roles'))

    for idx, value in enumerate(ordered_ids, start=1):
        try:
            role_id = int(value)
        except ValueError:
            continue
        role = db.session.get(MemberRole, role_id)
        if role:
            role.sort_order = idx * 10
    db.session.commit()
    flash('Reihenfolge gespeichert.', 'success')
    return redirect(url_for('master_data.member_roles'))


@bp.route('/role-permissions', methods=['GET'])
@login_required
@admin_required
def role_permissions(current_user):
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name).all()
    roles = MemberRole.query.filter_by(is_active=True).order_by(MemberRole.sort_order, MemberRole.label).all()
    entries = RolePermission.query.order_by(RolePermission.sort_order, RolePermission.member_role_key, RolePermission.service_name, RolePermission.permission_key).all()

    service_names = ['*'] + [service.name for service in services]
    matrix_lookup = {}
    for entry in entries:
        if not entry.is_active:
            continue
        permission_key = entry.permission_key
        if permission_key == 'write':
            permission_key = 'create'
        if permission_key not in CRUD_PERMISSIONS:
            continue
        matrix_lookup[f'{entry.member_role_key}|{entry.service_name}|{permission_key}'] = True

    return render_template(
        'master_data_role_permissions.html',
        current_user=current_user,
        services=services,
        roles=roles,
        entries=entries,
        service_names=service_names,
        permissions_catalog=CRUD_PERMISSIONS,
        matrix_lookup=matrix_lookup,
    )


@bp.route('/role-permissions/matrix-save', methods=['POST'])
@login_required
@admin_required
def role_permissions_matrix_save(current_user):
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name).all()
    roles = MemberRole.query.filter_by(is_active=True).order_by(MemberRole.sort_order, MemberRole.label).all()
    service_names = ['*'] + [service.name for service in services]

    changed = False
    order_idx = 1
    for role in roles:
        for service_name in service_names:
            for permission_key in CRUD_PERMISSIONS:
                field_name = f'perm__{role.key}__{service_name}__{permission_key}'
                should_be_active = request.form.get(field_name) == 'y'
                entry = RolePermission.query.filter_by(
                    member_role_key=role.key,
                    service_name=service_name,
                    permission_key=permission_key,
                ).first()

                if should_be_active:
                    sort_order = order_idx * 10
                    if not entry:
                        db.session.add(RolePermission(
                            member_role_key=role.key,
                            service_name=service_name,
                            permission_key=permission_key,
                            sort_order=sort_order,
                            is_active=True,
                        ))
                        changed = True
                    else:
                        if not entry.is_active or entry.sort_order != sort_order:
                            entry.is_active = True
                            entry.sort_order = sort_order
                            changed = True
                    order_idx += 1

                    # Transition support: keep legacy "write" in sync with "create".
                    if permission_key == 'create':
                        legacy_entry = RolePermission.query.filter_by(
                            member_role_key=role.key,
                            service_name=service_name,
                            permission_key='write',
                        ).first()
                        if not legacy_entry:
                            db.session.add(RolePermission(
                                member_role_key=role.key,
                                service_name=service_name,
                                permission_key='write',
                                sort_order=sort_order + 1,
                                is_active=True,
                            ))
                            changed = True
                        elif not legacy_entry.is_active:
                            legacy_entry.is_active = True
                            changed = True
                    continue

                if entry and entry.is_active:
                    entry.is_active = False
                    changed = True

                if permission_key == 'create':
                    legacy_entry = RolePermission.query.filter_by(
                        member_role_key=role.key,
                        service_name=service_name,
                        permission_key='write',
                    ).first()
                    if legacy_entry and legacy_entry.is_active:
                        legacy_entry.is_active = False
                        changed = True

    if changed:
        db.session.commit()
        flash('Rechte-Matrix gespeichert.', 'success')
    else:
        flash('Keine Änderungen in der Rechte-Matrix.', 'info')
    return redirect(url_for('master_data.role_permissions'))


@bp.route('/role-permissions/new', methods=['POST'])
@login_required
@admin_required
def role_permissions_new(current_user):
    member_role_key = (request.form.get('member_role_key') or '').strip().lower()
    service_name = (request.form.get('service_name') or '').strip() or '*'
    permission_key = (request.form.get('permission_key') or '').strip().lower()
    sort_order = request.form.get('sort_order', type=int)
    is_active = request.form.get('is_active') == 'y'

    if not member_role_key or not permission_key:
        flash('Rolle und Permission sind erforderlich.', 'danger')
        return redirect(url_for('master_data.role_permissions'))

    exists = RolePermission.query.filter_by(
        member_role_key=member_role_key,
        service_name=service_name,
        permission_key=permission_key,
    ).first()
    if exists:
        flash('Diese Berechtigung existiert bereits.', 'warning')
        return redirect(url_for('master_data.role_permissions'))

    if sort_order is None:
        sort_order = (RolePermission.query.count() + 1) * 10

    db.session.add(RolePermission(
        member_role_key=member_role_key,
        service_name=service_name,
        permission_key=permission_key,
        sort_order=sort_order,
        is_active=is_active,
    ))
    db.session.commit()
    flash('Berechtigung gespeichert.', 'success')
    return redirect(url_for('master_data.role_permissions'))


@bp.route('/role-permissions/<int:entry_id>/edit', methods=['POST'])
@login_required
@admin_required
def role_permissions_edit(current_user, entry_id):
    entry = db.session.get(RolePermission, entry_id)
    if not entry:
        flash('Berechtigung nicht gefunden.', 'danger')
        return redirect(url_for('master_data.role_permissions'))

    entry.sort_order = request.form.get('sort_order', type=int) or entry.sort_order
    entry.is_active = request.form.get('is_active') == 'y'
    db.session.commit()
    flash('Berechtigung gespeichert.', 'success')
    return redirect(url_for('master_data.role_permissions'))


@bp.route('/role-permissions/<int:entry_id>/delete', methods=['POST'])
@login_required
@admin_required
def role_permissions_delete(current_user, entry_id):
    entry = db.session.get(RolePermission, entry_id)
    if not entry:
        flash('Berechtigung nicht gefunden.', 'danger')
        return redirect(url_for('master_data.role_permissions'))

    db.session.delete(entry)
    db.session.commit()
    flash('Berechtigung gelöscht.', 'success')
    return redirect(url_for('master_data.role_permissions'))
