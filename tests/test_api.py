def test_internal_team_member_count(client, app):
    from app.extensions import db
    from app.models import Team, TeamMembership, User

    with app.app_context():
        team = Team.query.filter_by(code='U16').first()
        team_id = team.id
        team_code = team.code
        player = User(username='player-user', role='user', account_status='active', is_active=True)
        player.set_password('password123')
        coach = User(username='coach-user', role='coach', account_status='active', is_active=True)
        coach.set_password('password123')
        db.session.add(player)
        db.session.add(coach)
        db.session.flush()
        db.session.add(TeamMembership(user_id=player.id, team_id=team_id, member_role='player', is_active=True))
        db.session.add(TeamMembership(user_id=coach.id, team_id=team_id, member_role='coach', is_active=True))
        db.session.commit()

    response = client.get(
        f'/api/internal/teams/{team_code}/active-member-count',
        headers={'X-TT-Internal-Secret': 'test-internal-secret'},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['team_code'] == team_code
    assert payload['active_member_count'] >= 2
    assert payload['active_player_count'] == 1


def test_internal_user_endpoint_returns_user_payload(client, app):
    from app.extensions import db
    from app.models import Team, TeamMembership, User

    with app.app_context():
        team = Team.query.filter_by(code='U16').first()
        user = User(username='player-two', role='user', account_status='active', is_active=True)
        user.set_password('password123')
        db.session.add(user)
        db.session.flush()
        db.session.add(TeamMembership(user_id=user.id, team_id=team.id, member_role='player', is_active=True))
        db.session.commit()
        user_id = user.id

    response = client.get(
        f'/api/users/{user_id}',
        headers={'X-TT-Internal-Secret': 'test-internal-secret'},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['id'] == user_id
    assert payload['username'] == 'player-two'
    assert payload['team_roles']


def test_internal_team_players_returns_only_active_players(client, app):
    from app.extensions import db
    from app.models import Team, TeamMembership, User

    with app.app_context():
        team = Team.query.filter_by(code='U16').first()
        team_code = team.code
        player = User(username='player-three', role='user', account_status='active', is_active=True)
        player.set_password('password123')
        coach = User(username='coach-three', role='coach', account_status='active', is_active=True)
        coach.set_password('password123')
        db.session.add(player)
        db.session.add(coach)
        db.session.flush()
        db.session.add(TeamMembership(user_id=player.id, team_id=team.id, member_role='player', is_active=True))
        db.session.add(TeamMembership(user_id=coach.id, team_id=team.id, member_role='coach', is_active=True))
        db.session.commit()

    response = client.get(
        f'/api/internal/teams/{team_code}/players',
        headers={'X-TT-Internal-Secret': 'test-internal-secret'},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['team_code'] == team_code
    assert len(payload['players']) == 1
    assert payload['players'][0]['username'] == 'player-three'


def test_team_manager_update_accepts_team_betreuer_role(client, app):
    from app.extensions import db
    from app.models import Team, User

    with app.app_context():
        team = Team.query.filter_by(code='U16').first()
        approver = User(username='admin-user', role='admin', account_status='active', is_active=True)
        approver.set_password('password123')
        target = User(username='target-user', role='user', account_status='active', is_active=True)
        target.set_password('password123')
        db.session.add(approver)
        db.session.add(target)
        db.session.flush()
        approver_id = approver.id
        target_id = target.id
        team_id = team.id
        db.session.commit()

    response = client.post(
        f'/api/team-manager/members/{target_id}',
        json={
            'approver_auth_user_id': approver_id,
            'active_memberships': [
                {'team_id': team_id, 'member_role': 'team_betreuer'},
            ],
        },
        headers={'X-TT-Internal-Secret': 'test-internal-secret'},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['user']['team_roles'][str(team_id)] == ['team_betreuer']
