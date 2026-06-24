from wtforms import Form, StringField, PasswordField, SelectField, BooleanField, IntegerField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, URL, NumberRange


class LoginForm(Form):
    username = StringField('Benutzername', validators=[DataRequired(), Length(max=64)])
    password = PasswordField('Passwort', validators=[DataRequired()])


class RegisterForm(Form):
    username = StringField('Benutzername', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-Mail', validators=[Optional(), Email(), Length(max=255)])
    first_name = StringField('Vorname', validators=[DataRequired(), Length(max=80)])
    last_name = StringField('Nachname', validators=[DataRequired(), Length(max=80)])
    requested_team_id = SelectField('Mannschaft', coerce=int, validators=[DataRequired()])
    requested_member_role = SelectField(
        'Rolle im Team',
        choices=[('player', 'Spieler'), ('coach', 'Coach'), ('head_coach', 'Head Coach')],
        validators=[DataRequired()],
    )
    password = PasswordField('Passwort', validators=[DataRequired(), Length(min=8, max=128)])
    password_confirm = PasswordField(
        'Passwort wiederholen',
        validators=[DataRequired(), EqualTo('password', message='Die Passwoerter stimmen nicht ueberein.')],
    )


class UserForm(Form):
    username = StringField('Benutzername', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-Mail', validators=[Optional(), Email(), Length(max=255)])
    first_name = StringField('Vorname', validators=[Optional(), Length(max=80)])
    last_name = StringField('Nachname', validators=[Optional(), Length(max=80)])
    password = PasswordField('Passwort', validators=[Optional(), Length(min=8, max=128)])
    role = SelectField('Rolle', choices=[('user', 'Benutzer'), ('admin', 'Administrator')], default='user')
    account_status = SelectField(
        'Kontostatus',
        choices=[
            ('draft', 'Profil noch offen'),
            ('pending', 'Wartet auf Freigabe'),
            ('active', 'Aktiv'),
            ('suspended', 'Gesperrt'),
        ],
        default='active',
    )
    requested_team_id = SelectField('Beantragte Mannschaft', coerce=int, validators=[Optional()])
    requested_member_role = SelectField(
        'Beantragte Rolle',
        choices=[('', 'Keine'), ('player', 'Spieler'), ('coach', 'Coach'), ('head_coach', 'Head Coach'), ('team_manager', 'Team-Manager')],
        validators=[Optional()],
    )
    profile_complete = BooleanField('Profil vollstaendig', default=False)
    is_active = BooleanField('Aktiv', default=True)


class ServiceForm(Form):
    name = StringField('Name', validators=[DataRequired(), Length(max=64)])
    url = StringField('URL', validators=[DataRequired(), URL(), Length(max=255)])
    icon = StringField('Bootstrap Icon', validators=[Optional(), Length(max=64)], default='grid')
    description = TextAreaField('Beschreibung', validators=[Optional(), Length(max=255)])
    required_role = SelectField('Mindestrolle', choices=[('user', 'Benutzer'), ('admin', 'Administrator')])
    is_active = BooleanField('Aktiv', default=True)
    sort_order = IntegerField('Reihenfolge', validators=[Optional(), NumberRange(min=0)], default=0)
