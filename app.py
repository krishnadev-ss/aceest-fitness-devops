"""ACEest Fitness & Gym - Flask web service.

Web port of the ACEest desktop scripts (baseline v1.0 up to v3.2.4, kept in
``legacy/``). It exposes the gym's training programs, calorie/BMI calculators,
client management, weekly adherence, workout and body-metric logging,
membership tracking, a program generator, client reports and user login
through a JSON API backed by SQLite.
"""
import csv
import io
import os
import random
import sqlite3
from datetime import date

from flask import Flask, Response, g, jsonify, render_template_string, request
from werkzeug.security import check_password_hash, generate_password_hash

# PBKDF2 is available in every Python/OpenSSL build (scrypt is not).
HASH_METHOD = "pbkdf2:sha256"

APP_VERSION = "2.0.2"

# --------------------------------------------------------------------------
# Domain data (carried over from the baseline ACEest script)
# --------------------------------------------------------------------------
PROGRAMS = {
    "FL": {
        "name": "Fat Loss",
        "workout": [
            "Mon: Back Squat 5x5 + Core",
            "Tue: EMOM 20min Assault Bike",
            "Wed: Bench Press + 21-15-9",
            "Thu: Deadlift + Box Jumps",
            "Fri: Zone 2 Cardio 30min",
        ],
        "diet": [
            "Breakfast: Egg Whites + Oats",
            "Lunch: Grilled Chicken + Brown Rice",
            "Dinner: Fish Curry + Millet Roti",
            "Target: ~2000 kcal",
        ],
        "calorie_factor": 22,
    },
    "MG": {
        "name": "Muscle Gain",
        "workout": [
            "Mon: Squat 5x5",
            "Tue: Bench 5x5",
            "Wed: Deadlift 4x6",
            "Thu: Front Squat 4x8",
            "Fri: Incline Press 4x10",
            "Sat: Barbell Rows 4x10",
        ],
        "diet": [
            "Breakfast: Eggs + Peanut Butter Oats",
            "Lunch: Chicken Biryani",
            "Dinner: Mutton Curry + Rice",
            "Target: ~3200 kcal",
        ],
        "calorie_factor": 35,
    },
    "BG": {
        "name": "Beginner",
        "workout": [
            "Full Body Circuit: Air Squats, Ring Rows, Push-ups",
            "Focus: Technique & Consistency",
        ],
        "diet": [
            "Balanced Tamil Meals: Idli / Dosa / Rice + Dal",
            "Protein Target: 120g/day",
        ],
        "calorie_factor": 26,
    },
}

GYM_METRICS = {
    "capacity_users": 150,
    "area_sqft": 10000,
    "break_even_members": 250,
}

# Plan templates used by the program generator (baseline v3.1.2 / v3.2.4).
PROGRAM_TEMPLATES = {
    "FL": ["Full Body HIIT", "Circuit Training", "Cardio + Weights"],
    "MG": ["Push/Pull/Legs", "Upper/Lower Split", "Full Body Strength"],
    "BG": ["Full Body 3x/week", "Light Strength + Mobility"],
}

WORKOUT_TYPES = ("Strength", "Hypertrophy", "Cardio", "Mobility")
MEMBERSHIP_STATUSES = ("Active", "Paused", "Expired")
ROLES = ("Admin", "Trainer", "Member")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT UNIQUE NOT NULL,
    age              INTEGER NOT NULL,
    weight_kg        REAL NOT NULL,
    program          TEXT NOT NULL,
    calories         INTEGER NOT NULL,
    height_cm        REAL,
    target_weight    REAL,
    target_adherence INTEGER,
    plan             TEXT,
    membership_status TEXT NOT NULL DEFAULT 'Active',
    membership_end   TEXT
);
CREATE TABLE IF NOT EXISTS progress (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    week        TEXT NOT NULL,
    adherence   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workouts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name  TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    workout_type TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    notes        TEXT
);
CREATE TABLE IF NOT EXISTS exercises (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    sets       INTEGER NOT NULL,
    reps       INTEGER NOT NULL,
    weight_kg  REAL
);
CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    weight_kg   REAL,
    waist_cm    REAL,
    bodyfat     REAL
);
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL
);
"""

# Columns added after v1.0.0; older databases are upgraded in place.
CLIENT_MIGRATIONS = {
    "height_cm": "REAL",
    "target_weight": "REAL",
    "target_adherence": "INTEGER",
    "plan": "TEXT",
    "membership_status": "TEXT NOT NULL DEFAULT 'Active'",
    "membership_end": "TEXT",
}

CLIENT_COLUMNS = (
    "name, age, weight_kg, program, calories, height_cm, target_weight, "
    "target_adherence, plan, membership_status, membership_end"
)

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>ACEest Fitness &amp; Gym</title>
<style>
 body{font-family:Helvetica,Arial,sans-serif;background:#1a1a1a;color:#eee;
      margin:0}
 header{background:#d4af37;color:#000;padding:20px;text-align:center}
 main{max-width:900px;margin:auto;padding:20px}
 section{border:1px solid #d4af37;border-radius:6px;padding:12px 18px;
         margin-bottom:16px}
 h2{color:#d4af37;margin-top:4px} code{color:#d4af37}
</style></head><body>
<header><h1>ACEest Functional Fitness</h1><small>v{{ version }}</small></header>
<main>
{% for code, p in programs.items() %}
<section>
 <h2>{{ p.name }} ({{ code }})</h2>
 <b>Weekly workout</b><ul>{% for w in p.workout %}<li>{{ w }}</li>{% endfor %}</ul>
 <b>Nutrition</b><ul>{% for d in p.diet %}<li>{{ d }}</li>{% endfor %}</ul>
</section>
{% endfor %}
<p>Capacity: {{ metrics.capacity_users }} users &middot;
   Area: {{ metrics.area_sqft }} sq ft &middot;
   Break-even: {{ metrics.break_even_members }} members</p>
<p>JSON API: <code>/health</code>, <code>/api/programs</code>,
   <code>/api/calories</code>, <code>/api/bmi</code>,
   <code>/api/clients</code> (progress, workouts, metrics, membership,
   program generator, report), <code>/api/login</code></p>
</main></body></html>
"""


# --------------------------------------------------------------------------
# Pure business logic (unit-testable without Flask)
# --------------------------------------------------------------------------
class ValidationError(ValueError):
    """Raised when client-supplied data fails validation."""


class _HTTPResponse(Exception):
    """Internal: carries a ready-made JSON error response out of a view."""

    def __init__(self, response):
        super().__init__(response.status)
        self.response = response


def _positive_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"'{field}' must be a number")
    if value <= 0:
        raise ValidationError(f"'{field}' must be greater than 0")
    return float(value)


def get_program(code):
    """Return the program for a code (case-insensitive) or raise."""
    key = str(code or "").strip().upper()
    if key not in PROGRAMS:
        raise ValidationError(
            f"unknown program '{code}'; choose one of {sorted(PROGRAMS)}"
        )
    return key, PROGRAMS[key]


def calculate_calories(weight_kg, program_code):
    """Daily calorie estimate = body weight (kg) x program calorie factor."""
    weight = _positive_number(weight_kg, "weight_kg")
    _, program = get_program(program_code)
    return int(weight * program["calorie_factor"])


def calculate_bmi(weight_kg, height_cm):
    """Return (bmi rounded to 1 dp, WHO category)."""
    weight = _positive_number(weight_kg, "weight_kg")
    height_m = _positive_number(height_cm, "height_cm") / 100
    bmi = round(weight / (height_m ** 2), 1)
    if bmi < 18.5:
        category = "Underweight"
    elif bmi < 25:
        category = "Normal"
    elif bmi < 30:
        category = "Overweight"
    else:
        category = "Obese"
    return bmi, category


def validate_client(data):
    """Validate a client payload and return a normalised dict."""
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("'name' is required")
    age = data.get("age")
    if isinstance(age, bool) or not isinstance(age, int) or not 10 <= age <= 100:
        raise ValidationError("'age' must be an integer between 10 and 100")
    code, _ = get_program(data.get("program"))
    weight = _positive_number(data.get("weight_kg"), "weight_kg")
    client = {
        "name": name,
        "age": age,
        "weight_kg": weight,
        "program": code,
        "calories": calculate_calories(weight, code),
    }
    client.update(validate_client_extras(data))
    return client


def _optional_positive(data, field):
    value = data.get(field)
    return None if value is None else _positive_number(value, field)


def validate_client_extras(data):
    """Optional profile fields added in baseline v2.2.4 - v3.2.4."""
    extras = {
        "height_cm": _optional_positive(data, "height_cm"),
        "target_weight": _optional_positive(data, "target_weight"),
        "target_adherence": None,
        "membership_status": validate_membership_status(
            data.get("membership_status", "Active")
        ),
        "membership_end": None,
    }
    if data.get("target_adherence") is not None:
        extras["target_adherence"] = validate_adherence(
            data.get("target_adherence"), "target_adherence"
        )
    if data.get("membership_end") is not None:
        extras["membership_end"] = validate_date(
            data.get("membership_end"), "membership_end"
        )
    return extras


def validate_adherence(value, field="adherence"):
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value <= 100:
        raise ValidationError(f"'{field}' must be an integer from 0 to 100")
    return value


def validate_date(value, field="date"):
    """Accept an ISO date string (YYYY-MM-DD) and return it normalised."""
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValidationError(f"'{field}' must be a date in YYYY-MM-DD format")


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"'{field}' must be a positive integer")
    return value


def validate_membership_status(value):
    status = str(value or "").strip().capitalize()
    if status not in MEMBERSHIP_STATUSES:
        raise ValidationError(
            f"'membership_status' must be one of {list(MEMBERSHIP_STATUSES)}"
        )
    return status


def validate_workout(data):
    """Validate a workout payload (baseline v2.2.4 'Log Workout')."""
    workout_type = str(data.get("workout_type") or "").strip().capitalize()
    if workout_type not in WORKOUT_TYPES:
        raise ValidationError(
            f"'workout_type' must be one of {list(WORKOUT_TYPES)}"
        )
    exercises = data.get("exercises") or []
    if not isinstance(exercises, list):
        raise ValidationError("'exercises' must be a list")
    clean = []
    for item in exercises:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise ValidationError("each exercise needs a 'name'")
        clean.append({
            "name": str(item["name"]).strip(),
            "sets": _positive_int(item.get("sets"), "sets"),
            "reps": _positive_int(item.get("reps"), "reps"),
            "weight_kg": _optional_positive(item, "weight_kg"),
        })
    return {
        "date": validate_date(data.get("date") or date.today().isoformat()),
        "workout_type": workout_type,
        "duration_min": _positive_int(data.get("duration_min", 60),
                                      "duration_min"),
        "notes": str(data.get("notes") or "").strip(),
        "exercises": clean,
    }


def validate_metrics(data):
    """Validate a body-metrics payload (weight, waist, body fat)."""
    entry = {
        "date": validate_date(data.get("date") or date.today().isoformat()),
        "weight_kg": _optional_positive(data, "weight_kg"),
        "waist_cm": _optional_positive(data, "waist_cm"),
        "bodyfat": _optional_positive(data, "bodyfat"),
    }
    if entry["bodyfat"] is not None and entry["bodyfat"] >= 100:
        raise ValidationError("'bodyfat' must be below 100")
    if all(entry[k] is None for k in ("weight_kg", "waist_cm", "bodyfat")):
        raise ValidationError(
            "provide at least one of 'weight_kg', 'waist_cm', 'bodyfat'"
        )
    return entry


def generate_plan(program_code, rng=None):
    """Pick a training plan for the client's program (v3.x generator)."""
    code, _ = get_program(program_code)
    return (rng or random).choice(PROGRAM_TEMPLATES[code])


def membership_info(status, end, today=None):
    """Membership state with days remaining; past end dates read Expired."""
    today = today or date.today()
    days_left = None
    if end:
        days_left = (date.fromisoformat(end) - today).days
        if days_left < 0:
            status = "Expired"
    return {"status": status, "end": end, "days_remaining": days_left}


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------
def create_app(config=None):
    app = Flask(__name__)
    app.config["DATABASE"] = os.environ.get("ACEEST_DB", "aceest_fitness.db")
    app.config.update(config or {})

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"], timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        existing = {r["name"] for r in db.execute("PRAGMA table_info(clients)")}
        for column, ddl in CLIENT_MIGRATIONS.items():
            if column not in existing:
                try:
                    db.execute(f"ALTER TABLE clients ADD COLUMN {column} {ddl}")
                except sqlite3.OperationalError as err:
                    # Another gunicorn worker added it first.
                    if "duplicate column" not in str(err):  # pragma: no cover
                        raise
        # OR IGNORE: several workers may seed the admin user at the same time.
        if db.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone() \
                is None:
            db.execute(
                "INSERT OR IGNORE INTO users VALUES ('admin', ?, 'Admin')",
                (generate_password_hash(
                    os.environ.get("ACEEST_ADMIN_PASSWORD", "admin"),
                    method=HASH_METHOD),),
            )
        db.commit()

    # ---- error handling ---------------------------------------------------
    @app.errorhandler(ValidationError)
    def handle_validation(err):
        return jsonify(error=str(err)), 400

    @app.errorhandler(_HTTPResponse)
    def handle_http_response(err):
        return err.response

    @app.errorhandler(404)
    def handle_404(_err):
        return jsonify(error="resource not found"), 404

    @app.errorhandler(405)
    def handle_405(_err):
        return jsonify(error="method not allowed"), 405

    def json_body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError("request body must be a JSON object")
        return data

    def find_client(name):
        return get_db().execute(
            f"SELECT {CLIENT_COLUMNS} FROM clients WHERE name = ?", (name,)
        ).fetchone()

    def client_or_404(name):
        row = find_client(name)
        if row is None:
            abort_json(404, f"client '{name}' not found")
        return row

    def abort_json(status, message):
        response = jsonify(error=message)
        response.status_code = status
        raise _HTTPResponse(response)

    # ---- pages & service endpoints ---------------------------------------
    @app.get("/")
    def index():
        return render_template_string(
            INDEX_HTML, programs=PROGRAMS, metrics=GYM_METRICS,
            version=APP_VERSION,
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="aceest-fitness",
                       version=APP_VERSION)

    @app.get("/api/metrics")
    def metrics():
        return jsonify(GYM_METRICS)

    # ---- programs ---------------------------------------------------------
    @app.get("/api/programs")
    def list_programs():
        return jsonify(PROGRAMS)

    @app.get("/api/programs/<code>")
    def program_detail(code):
        try:
            key, program = get_program(code)
        except ValidationError:
            return jsonify(error=f"program '{code}' not found"), 404
        return jsonify(code=key, **program)

    # ---- calculators ------------------------------------------------------
    @app.post("/api/calories")
    def calories():
        data = json_body()
        code, _ = get_program(data.get("program"))
        return jsonify(
            program=code,
            weight_kg=data.get("weight_kg"),
            calories=calculate_calories(data.get("weight_kg"), code),
        )

    @app.post("/api/bmi")
    def bmi():
        data = json_body()
        value, category = calculate_bmi(
            data.get("weight_kg"), data.get("height_cm")
        )
        return jsonify(bmi=value, category=category)

    # ---- clients ----------------------------------------------------------
    @app.get("/api/clients")
    def list_clients():
        rows = get_db().execute(
            f"SELECT {CLIENT_COLUMNS} FROM clients ORDER BY name"
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/clients")
    def create_client():
        client = validate_client(json_body())
        db = get_db()
        try:
            db.execute(
                "INSERT INTO clients (name, age, weight_kg, program, calories,"
                " height_cm, target_weight, target_adherence,"
                " membership_status, membership_end)"
                " VALUES (:name, :age, :weight_kg, :program, :calories,"
                " :height_cm, :target_weight, :target_adherence,"
                " :membership_status, :membership_end)",
                client,
            )
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify(
                error=f"client '{client['name']}' already exists"
            ), 409
        return jsonify(dict(find_client(client["name"]))), 201

    @app.get("/api/clients/<name>")
    def get_client(name):
        row = find_client(name)
        if row is None:
            return jsonify(error=f"client '{name}' not found"), 404
        return jsonify(dict(row))

    @app.delete("/api/clients/<name>")
    def delete_client(name):
        db = get_db()
        deleted = db.execute(
            "DELETE FROM clients WHERE name = ?", (name,)
        ).rowcount
        db.commit()
        if not deleted:
            return jsonify(error=f"client '{name}' not found"), 404
        return "", 204

    # ---- weekly progress --------------------------------------------------
    @app.post("/api/clients/<name>/progress")
    def add_progress(name):
        if find_client(name) is None:
            return jsonify(error=f"client '{name}' not found"), 404
        data = json_body()
        adherence = validate_adherence(data.get("adherence"))
        week = str(data.get("week") or date.today().strftime("Week %V - %G"))
        db = get_db()
        db.execute(
            "INSERT INTO progress (client_name, week, adherence) "
            "VALUES (?, ?, ?)", (name, week, adherence),
        )
        db.commit()
        return jsonify(client=name, week=week, adherence=adherence), 201

    @app.get("/api/clients/<name>/progress")
    def get_progress(name):
        if find_client(name) is None:
            return jsonify(error=f"client '{name}' not found"), 404
        rows = get_db().execute(
            "SELECT week, adherence FROM progress "
            "WHERE client_name = ? ORDER BY id", (name,)
        ).fetchall()
        entries = [dict(r) for r in rows]
        average = (
            round(sum(e["adherence"] for e in entries) / len(entries), 1)
            if entries else None
        )
        return jsonify(client=name, entries=entries,
                       average_adherence=average)

    # ---- profile update (v2.2.4 'Save Client' with height / goals) --------
    @app.patch("/api/clients/<name>")
    def update_client(name):
        current = dict(client_or_404(name))
        data = json_body()
        merged = {**current, **{k: v for k, v in data.items() if k != "name"}}
        merged["name"] = name
        client = validate_client(merged)
        client["plan"] = current["plan"]
        db = get_db()
        db.execute(
            "UPDATE clients SET age=:age, weight_kg=:weight_kg,"
            " program=:program, calories=:calories, height_cm=:height_cm,"
            " target_weight=:target_weight, target_adherence=:target_adherence,"
            " membership_status=:membership_status,"
            " membership_end=:membership_end WHERE name=:name",
            client,
        )
        db.commit()
        return jsonify(dict(find_client(name)))

    # ---- workouts & exercises (v2.2.4) -------------------------------------
    @app.post("/api/clients/<name>/workouts")
    def add_workout(name):
        client_or_404(name)
        workout = validate_workout(json_body())
        db = get_db()
        cur = db.execute(
            "INSERT INTO workouts (client_name, date, workout_type,"
            " duration_min, notes) VALUES (?, ?, ?, ?, ?)",
            (name, workout["date"], workout["workout_type"],
             workout["duration_min"], workout["notes"]),
        )
        workout_id = cur.lastrowid
        db.executemany(
            "INSERT INTO exercises (workout_id, name, sets, reps, weight_kg)"
            " VALUES (?, ?, ?, ?, ?)",
            [(workout_id, e["name"], e["sets"], e["reps"], e["weight_kg"])
             for e in workout["exercises"]],
        )
        db.commit()
        return jsonify(id=workout_id, client=name, **workout), 201

    @app.get("/api/clients/<name>/workouts")
    def list_workouts(name):
        client_or_404(name)
        db = get_db()
        workouts = [dict(r) for r in db.execute(
            "SELECT id, date, workout_type, duration_min, notes FROM workouts"
            " WHERE client_name = ? ORDER BY date DESC, id DESC", (name,)
        )]
        for workout in workouts:
            workout["exercises"] = [dict(r) for r in db.execute(
                "SELECT name, sets, reps, weight_kg FROM exercises"
                " WHERE workout_id = ? ORDER BY id", (workout["id"],)
            )]
        return jsonify(client=name, workouts=workouts,
                       total_minutes=sum(w["duration_min"] for w in workouts))

    # ---- body metrics + weight trend (v2.2.4) ------------------------------
    @app.post("/api/clients/<name>/metrics")
    def add_metrics(name):
        client_or_404(name)
        entry = validate_metrics(json_body())
        db = get_db()
        db.execute(
            "INSERT INTO metrics (client_name, date, weight_kg, waist_cm,"
            " bodyfat) VALUES (?, ?, ?, ?, ?)",
            (name, entry["date"], entry["weight_kg"], entry["waist_cm"],
             entry["bodyfat"]),
        )
        db.commit()
        return jsonify(client=name, **entry), 201

    @app.get("/api/clients/<name>/metrics")
    def list_metrics(name):
        client_or_404(name)
        entries = [dict(r) for r in get_db().execute(
            "SELECT date, weight_kg, waist_cm, bodyfat FROM metrics"
            " WHERE client_name = ? ORDER BY date, id", (name,)
        )]
        trend = [{"date": e["date"], "weight_kg": e["weight_kg"]}
                 for e in entries if e["weight_kg"] is not None]
        return jsonify(client=name, entries=entries, weight_trend=trend)

    # ---- membership (v3.2.4) -----------------------------------------------
    @app.get("/api/clients/<name>/membership")
    def get_membership(name):
        row = client_or_404(name)
        return jsonify(client=name, **membership_info(
            row["membership_status"], row["membership_end"]))

    @app.put("/api/clients/<name>/membership")
    def set_membership(name):
        client_or_404(name)
        data = json_body()
        status = validate_membership_status(data.get("status", "Active"))
        end = data.get("end")
        end = validate_date(end, "end") if end is not None else None
        db = get_db()
        db.execute(
            "UPDATE clients SET membership_status = ?, membership_end = ?"
            " WHERE name = ?", (status, end, name),
        )
        db.commit()
        return jsonify(client=name, **membership_info(status, end))

    # ---- program generator (v3.1.2 'Generate AI Program') ------------------
    @app.post("/api/clients/<name>/program/generate")
    def generate_program(name):
        row = client_or_404(name)
        data = request.get_json(silent=True) or {}
        seed = data.get("seed") if isinstance(data, dict) else None
        rng = random.Random(seed) if seed is not None else None
        plan = generate_plan(row["program"], rng)
        db = get_db()
        db.execute("UPDATE clients SET plan = ? WHERE name = ?", (plan, name))
        db.commit()
        return jsonify(client=name, program=row["program"], plan=plan)

    # ---- client report (replaces v3.1.2 PDF report) ------------------------
    @app.get("/api/clients/<name>/report")
    def client_report(name):
        profile = dict(client_or_404(name))
        db = get_db()
        weeks, avg = db.execute(
            "SELECT COUNT(*), AVG(adherence) FROM progress"
            " WHERE client_name = ?", (name,)
        ).fetchone()
        last_metric = db.execute(
            "SELECT date, weight_kg, waist_cm, bodyfat FROM metrics"
            " WHERE client_name = ? ORDER BY date DESC, id DESC LIMIT 1", (name,)
        ).fetchone()
        sessions, minutes = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration_min), 0) FROM workouts"
            " WHERE client_name = ?", (name,)
        ).fetchone()
        bmi = None
        if profile["height_cm"]:
            value, category = calculate_bmi(profile["weight_kg"],
                                            profile["height_cm"])
            bmi = {"value": value, "category": category}
        return jsonify(
            profile=profile,
            program=PROGRAMS[profile["program"]]["name"],
            bmi=bmi,
            goals={"target_weight": profile["target_weight"],
                   "target_adherence": profile["target_adherence"]},
            progress={"weeks_logged": weeks,
                      "average_adherence": round(avg, 1) if avg else None},
            workouts={"sessions": sessions, "total_minutes": minutes},
            last_metrics=dict(last_metric) if last_metric else None,
            membership=membership_info(profile["membership_status"],
                                       profile["membership_end"]),
        )

    # ---- CSV export (v1.1.2 'Export CSV') ----------------------------------
    @app.get("/api/export/clients.csv")
    def export_clients_csv():
        rows = get_db().execute(
            f"SELECT {CLIENT_COLUMNS} FROM clients ORDER BY name"
        ).fetchall()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([c.strip() for c in CLIENT_COLUMNS.split(",")])
        writer.writerows([tuple(r) for r in rows])
        return Response(
            buffer.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition":
                     "attachment; filename=aceest_clients.csv"},
        )

    # ---- users & login (v3.1.2 role-based login) ---------------------------
    @app.post("/api/login")
    def login():
        data = json_body()
        row = get_db().execute(
            "SELECT username, password_hash, role FROM users WHERE username = ?",
            (str(data.get("username") or ""),),
        ).fetchone()
        if row is None or not check_password_hash(
                row["password_hash"], str(data.get("password") or "")):
            return jsonify(error="invalid username or password"), 401
        return jsonify(username=row["username"], role=row["role"])

    @app.post("/api/users")
    def create_user():
        data = json_body()
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        role = str(data.get("role") or "Member").strip().capitalize()
        if not username or len(password) < 4:
            raise ValidationError(
                "'username' is required and 'password' needs 4+ characters"
            )
        if role not in ROLES:
            raise ValidationError(f"'role' must be one of {list(ROLES)}")
        db = get_db()
        try:
            db.execute("INSERT INTO users VALUES (?, ?, ?)",
                       (username, generate_password_hash(password, method=HASH_METHOD),
                        role))
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify(error=f"user '{username}' already exists"), 409
        return jsonify(username=username, role=role), 201

    return app


if __name__ == "__main__":
    create_app().run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
    )
