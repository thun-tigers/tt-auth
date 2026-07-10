# tt-auth

Zentraler Identity- und SSO-Service der Thun-Tigers-Plattform.

## Zweck

`tt-auth` verwaltet Benutzerkonten, Rollen und Team-Mitgliedschaften und stellt
sich als Anmeldestelle vor die Microservices der Plattform. Die anderen
Services (`tt-members`, `tt-agenda`, `tt-analytics`, `tt-attendance`,
`tt-infra`) besitzen keinen eigenen Login, sondern uebernehmen Identitaeten
per SSO-Launch von hier.

## Architektur-Kontext

`tt-auth` ist ein Flask-Service (Gunicorn, Port 5000 im Container) mit
PostgreSQL als Datenbank. Er ist der einzige Ort in der Plattform, an dem
Passwoerter und Kontodaten liegen.

Downstream-Services:

- `tt-members` — Profile, Teams, Mitgliedschaftsverwaltung
- `tt-agenda` — Trainings- und Terminverwaltung
- `tt-analytics` — Spielanalyse, Scouting, Video
- `tt-attendance` — Trainingsanmeldung
- `tt-infra` — Plattform-Admin, Backups, Betrieb

Betrieb und Reverse-Proxy-Setup werden in `tt-infra` beschrieben, siehe
`../tt-infra/docs/HANDOFF_CENTRAL_CONFIG_AND_PROXY.md`.

## Auth- und SSO-Konzept

### Rollen

Zwei Plattformrollen im User-Modell:

- `admin` — voller Zugriff, Bootstrap ueber `DEFAULT_ADMIN_USERNAME` /
  `DEFAULT_ADMIN_PASSWORD`. Plattform-Admins erhalten beim Startup
  automatisch aktiven Admin-Zugriff auf jeden aktiven Service
  (`_bootstrap_platform_admin_access`).
- `user` — Standardrolle. Team-Mitgliedschaften und ihre Member-Rollen
  (`player`, `coach`, `head_coach`, `team_manager`, `team_betreuer`)
  bestimmen die feingranularen Rechte.

Zusaetzlich existiert `account_status` mit den Werten `draft`, `pending`,
`active`, `suspended`. `can_login` ist true fuer `draft`, `pending` und
`active`, damit ein neu registrierter Benutzer sein Profil noch
vervollstaendigen kann.

### JWT-Cookie `tt_jwt`

Nach erfolgreichem Login setzt `tt-auth` ein HTTP-only-Cookie namens
`tt_jwt` (siehe `Config.JWT_COOKIE_NAME`). Das Token ist HS256-signiert mit
`SECRET_KEY`. Konfigurierbar:

- `JWT_EXPIRY_HOURS` (Default 8) — Laufzeit
- `JWT_COOKIE_DOMAIN` — Cookie-Scope; muss zur gemeinsamen Root-Domain der
  Services passen, damit Downstream-Services das Cookie nicht brauchen,
  aber der Logout-Cleanup mehrere Domain-Varianten trifft
- `JWT_COOKIE_SECURE` — `true` in Produktion (HTTPS)

Payload (siehe `app/jwt_utils.py::generate_jwt`):

- `sub`, `username`, `role`, `account_status`, `profile_complete`
- `memberships`, `pending_memberships`, `teams`, `member_roles`
- `role_permissions` — pro Servicename Liste erlaubter Permission-Keys,
  hergeleitet aus der Tabelle `role_permissions` und den Member-Rollen des
  Benutzers
- `permissions` — flache, sortierte Liste (`profile:read`,
  `service:<name>:<key>`, `team:<code>:read|write|admin`); fuer Admins
  reduziert sich das auf `['*']`
- `iat`, `exp`

### SSO-Launch-Flow

Auf dem Dashboard fuehrt jeder Service-Kachel zu
`/launch/<service_id>` (`app/routes/dashboard.py::launch_service`).
Der Endpoint:

1. Prueft Login, aktives Konto und `ServiceAccess`-Eintrag des Benutzers.
2. Ermittelt die Audience aus dem Servicenamen (`tt-<name>`) und die
   effektive Rolle (Plattform-Admins wirken immer als `admin`).
3. Erzeugt ein kurzlebiges SSO-Token
   (`app/jwt_utils.py::generate_sso_token`, HS256 signiert mit
   `SSO_SHARED_SECRET`, TTL `SSO_TOKEN_EXPIRY_SECONDS`, Default 60s,
   `jti` als UUID).
4. Redirect nach `<service.url>/auth/sso?token=...` mit optionalem `next`.

Downstream-Services validieren das Token mit demselben
`SSO_SHARED_SECRET` und der erwarteten Audience.

### Interne Service-zu-Service-API

Blueprint `api` unter `/api/` ist rein maschinell und wird ueber den
Header `X-TT-Internal-Secret` autorisiert (`INTERNAL_API_SECRET`,
`app/routes/api.py::_authorized`). Die interne API liefert
Benutzerdaten, Team-Manager-Sichten und die Approval-Aktionen fuer
`tt-members`.

### Selbstregistrierung mit Approval

`/register` legt einen Benutzer mit `account_status='draft'`,
`profile_complete=False` und einer inaktiven `TeamMembership` fuer das
gewuenschte Team an. Nach dem Profil-Upsert in `tt-members` setzt dieses
den Status ueber `POST /api/users/<id>/profile-complete` auf `pending`.
Die Freigabe erfolgt durch Admins oder Team-Manager (UI unter `/users`
oder interne API `/api/team-manager/approve-user` /
`.../reject-user`); jede Entscheidung wird als `UserReviewEvent`
protokolliert.

## Endpunkte

Kein API-Prefix ausser bei den Blueprints mit `url_prefix`. Verifiziert
aus `app/routes/`:

### Auth (`app/routes/auth.py`)

- `GET/POST /login` — Login-Form, Rate-Limit 20/min auf POST
- `GET/POST /register` — Selbstregistrierung, Rate-Limit 10/h auf POST
- `GET /logout`

### Dashboard (`app/routes/dashboard.py`)

- `GET /health` — `{"status": "ok"}`
- `GET /` — Service-Kacheln, unterstuetzt `?next_service=` und `?next=`
  fuer Auto-Launch
- `GET/POST /profile` — Profildaten, Passwort, Theme (`tt_theme`,
  `tt_theme_global`)
- `GET /launch/<service_id>` — SSO-Launch (siehe oben)

### Users-Admin (`app/routes/users.py`, `url_prefix='/users'`)

- `GET /users/` — Liste
- `GET /users/<id>/reviews` — Approval-Historie
- `GET/POST /users/new`
- `GET/POST /users/<id>/edit`
- `POST /users/<id>/approve`
- `POST /users/<id>/delete`

### Services-Admin (`app/routes/services.py`, `url_prefix='/services'`)

- `GET /services/`
- `GET/POST /services/new`
- `GET/POST /services/<id>/edit`
- `POST /services/<id>/delete`

### Master-Data-Admin (`app/routes/master_data.py`,
`url_prefix='/master-data'`)

- `/positions` — Positionsverwaltung (Liste, Neu, Edit, Delete, Reorder)
- `/member-roles` — Member-Rollen (Liste, Neu, Edit, Delete, Reorder)
- `/role-permissions` — Rechtematrix (Liste, Matrix-Save, Neu, Edit,
  Delete)

### Interne API (`app/routes/api.py`, `url_prefix='/api'`)

Autorisierung: `X-TT-Internal-Secret: <INTERNAL_API_SECRET>`.

- `GET /api/users/<id>` — Benutzerdaten fuer Downstream-Services
- `POST /api/users/<id>/profile-complete` — Setzt `profile_complete=True`
  und (aus `draft`) `account_status=pending`
- `POST /api/users/<id>/profile` — Upsert Profilfelder
- `GET /api/team-manager/members`
- `GET/POST /api/team-manager/members/<target_user_id>`
- `GET /api/team-manager/pending-users`
- `POST /api/team-manager/approve-user`
- `POST /api/team-manager/reject-user`

## Datenmodell

Definitionen in `app/models.py`:

- `User` — Konto, Passwort-Hash, `role`, `account_status`,
  `profile_complete`, Profilfelder, `requested_team_id` /
  `requested_member_role` fuer den Registration-Antrag, Review-Metadaten.
- `Service` — Bekannte Downstream-Services mit `url`, `internal_url`,
  `required_role`, `sort_order`.
- `ServiceAccess` — n:m Benutzer/Service mit `role` (`user`/`admin`) und
  `is_active`; eindeutig pro Paar.
- `Team` — Teams mit `code`, `name`, `sort_order`.
- `MemberRole` — Katalog der Member-Rollen (Key + Label).
- `RolePermission` — Tripel `(member_role_key, service_name,
  permission_key)`, Wildcard `service_name='*'` ist erlaubt und wird in
  die JWT-Claims uebernommen.
- `TeamMembership` — n:m Benutzer/Team mit `member_role`; ein Antrag ist
  ein Eintrag mit `is_active=False`.
- `UserReviewEvent` — Audit-Log fuer Approve/Reject.

## Lokales Setup

Voraussetzungen: Python 3.12, PostgreSQL erreichbar (oder lokal ueber
Docker), Zugriff auf GitHub fuer die private Abhaengigkeit `tt-common`
(siehe `requirements.txt`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# SECRET_KEY, SQLALCHEMY_DATABASE_URI, SSO_SHARED_SECRET,
# INTERNAL_API_SECRET nach Bedarf anpassen

export FLASK_APP=run.py
flask run --port 5000
# alternativ: python run.py
```

Beim ersten Start legt der Service mit `AUTO_CREATE_DB=true` das Schema
und die Default-Datensaetze an (Admin-User, Services, Teams,
Member-Rollen, Role-Permissions).

## Docker / docker-compose

Das mitgelieferte `docker-compose.yml` startet den Service zusammen mit
einer eigenen Postgres-Instanz:

- Image: baut lokal, gepushtes Image `ghcr.io/swisi/tt-auth:latest`
- Port: `8085:5000`
- Postgres-Service `tt-postgres-auth` mit `postgres:16`, Healthcheck,
  eigenem Volume `tt-auth-postgres-data`
- Instance-Verzeichnis `/app/instance` als Volume `tt-auth-data`
- Die App wartet auf `service_healthy` des Postgres-Containers

```bash
docker compose up --build
# http://localhost:8085/
```

Im Produktions-Stack (`tt-infra`) laeuft der Service hinter dem
Reverse-Proxy; siehe die Beta-Compose-Files dort.

## Konfiguration

Alle Werte kommen aus Umgebungsvariablen (`app/config.py`, `python-dotenv`
laedt `.env`). Auszug der wichtigsten Variablen:

| Variable | Default | Zweck |
|---|---|---|
| `SECRET_KEY` | — | Flask-Secret und JWT-Signaturschluessel; im Produktionsmodus zwingend gesetzt |
| `SQLALCHEMY_DATABASE_URI` | `postgresql+psycopg://tt_auth:tt_auth_password@tt-postgres-auth:5432/tt_auth` | DB-Verbindung, alternativ `DATABASE_URL` |
| `JWT_EXPIRY_HOURS` | `8` | Laufzeit des `tt_jwt`-Cookies |
| `JWT_COOKIE_DOMAIN` | leer | Cookie-Domain fuer Multi-Host-Setups |
| `JWT_COOKIE_SECURE` | `false` | `true` fuer HTTPS-Produktion |
| `SSO_SHARED_SECRET` | fallback `SECRET_KEY` | Signatur der SSO-Launch-Tokens |
| `SSO_TOKEN_EXPIRY_SECONDS` | `60` | TTL des SSO-Launch-Tokens |
| `INTERNAL_API_SECRET` | `tt-internal-dev-secret-change-me` | Header-Secret fuer `/api/*` |
| `AUTO_CREATE_DB` | `true` | `db.create_all()` und Seed beim Startup |
| `CREATE_DEFAULT_USERS` | `true` | Legt Admin-Benutzer an, falls Tabelle leer |
| `CREATE_DEFAULT_SERVICES` | `true` | Legt/aktualisiert Standard-Services |
| `DEFAULT_ADMIN_USERNAME` | `admin` | Login des Bootstrap-Admin |
| `DEFAULT_ADMIN_PASSWORD` | `admin` | Passwort des Bootstrap-Admin; in Produktion zwingend anpassen |
| `DEFAULT_MEMBERS_URL` | `http://localhost:8088` | Public-URL fuer Service `members` |
| `DEFAULT_AGENDA_URL` | `http://localhost:8086` | Public-URL fuer Service `agenda` |
| `DEFAULT_ANALYTICS_URL` | `http://localhost:8087` | Public-URL fuer Service `analytics` |
| `DEFAULT_INFRA_URL` | `http://localhost:8084` | Public-URL fuer Service `infra` |
| `DEFAULT_ATTENDANCE_URL` | `http://localhost:8089` | Public-URL fuer Service `attendance` |
| `DEFAULT_*_INTERNAL_URL` | `http://host.docker.internal:<port>` | Service-zu-Service-URL innerhalb des Compose-Netzes |
| `TT_MEMBERS_INTERNAL_URL` | leer | Optionaler Override fuer Members-Anfragen aus `tt-auth` (Pending-Messages-Count) |
| `LOG_LEVEL` | `INFO` | Log-Level |
| `RATELIMIT_STORAGE_URI` | `memory://` | Flask-Limiter-Backend |

## Tests

```bash
pytest
```

Tests liegen in `tests/` und decken Login, JWT-Utilities, SSO-Launch und
das gemeinsame UI ab.

## Migrationen

`Flask-Migrate` ist installiert und initialisiert, das Verzeichnis
`migrations/` ist aktuell aber leer. Im Betrieb wird das Schema ueber
`AUTO_CREATE_DB=true` und die additiven Statements in
`_ensure_lightweight_schema_updates` (siehe `app/__init__.py`)
angelegt. Vor dem produktiven Rollout muss Alembic initialisiert und
diese Fallback-Logik durch echte Migrationen ersetzt werden.

## Release und Versionierung

- Version steht in `VERSION` (aktuell `0.1.16`).
- Container-Image: `ghcr.io/swisi/tt-auth:latest`
  (`docker-compose.yml`).
- Der Beta-/Prod-Stack wird in `tt-infra` gepflegt.

## Weiterfuehrend

- Roadmap und offene Themen: `docs/backlog.md`
- Plattform-Setup, Proxy, Zertifikate:
  `../tt-infra/docs/HANDOFF_CENTRAL_CONFIG_AND_PROXY.md`
