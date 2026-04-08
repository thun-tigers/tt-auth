from flask import Blueprint, render_template, redirect, url_for, request, flash
from ..extensions import db
from ..models import User, Service, ServiceAccess
from ..forms import UserForm
from . import login_required, admin_required

bp = Blueprint('users', __name__, url_prefix='/users')


@bp.route('/')
@login_required
@admin_required
def index(current_user):
    users = User.query.order_by(User.username).all()
    return render_template('users.html', users=users, current_user=current_user)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new(current_user):
    form = UserForm(request.form)
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order, Service.name).all()
    if request.method == 'POST' and form.validate():
        if User.query.filter_by(username=form.username.data).first():
            flash(f'Benutzername "{form.username.data}" ist bereits vergeben.', 'danger')
        elif not form.password.data:
            flash('Passwort ist erforderlich beim Erstellen eines Benutzers.', 'danger')
        else:
            user = User(username=form.username.data, role=form.role.data, is_active=form.is_active.data)
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
        if existing and existing.id != user.id:
            flash(f'Benutzername "{form.username.data}" ist bereits vergeben.', 'danger')
        else:
            user.username = form.username.data
            user.role = form.role.data
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
    )


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
        db.session.delete(user)
        db.session.commit()
        flash(f'Benutzer "{user.username}" gelöscht.', 'success')
    return redirect(url_for('users.index'))


def _sync_service_access(user, services, form_data):
    allowed_roles = {'none', 'user', 'admin'}
    existing = {access.service_id: access for access in user.service_access}

    for service in services:
        field_name = f'service_role_{service.id}'
        desired_role = (form_data.get(field_name) or 'none').strip().lower()
        if desired_role not in allowed_roles:
            desired_role = 'none'

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
