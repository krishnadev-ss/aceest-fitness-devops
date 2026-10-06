"""ACEest Fitness & Gym - Flask web service.

Web port of the baseline ACEest desktop script. It exposes the gym's training
programs, a calorie/BMI calculator, and client + weekly-progress management
through a small JSON API backed by SQLite.
"""
import os
import sqlite3
from datetime import date

from flask import Flask, g, jsonify, render_template_string, request

APP_VERSION = "1.0.0"

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT UNIQUE NOT NULL,
    age       INTEGER NOT NULL,
    weight_kg REAL NOT NULL,
    program   TEXT NOT NULL,
    calories  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL REFERENCES clients(name) ON DELETE CASCADE,
    week        TEXT NOT NULL,
    adherence   INTEGER NOT NULL
);
"""

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
   <code>/api/clients</code></p>
</main></body></html>
"""


# --------------------------------------------------------------------------
# Pure business logic (unit-testable without Flask)
# --------------------------------------------------------------------------
class ValidationError(ValueError):
    """Raised when client-supplied data fails validation."""


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
    return {
        "name": name,
        "age": age,
        "weight_kg": weight,
        "program": code,
        "calories": calculate_calories(weight, code),
    }


def validate_adherence(value):
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value <= 100:
        raise ValidationError("'adherence' must be an integer from 0 to 100")
    return value


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------
def create_app(config=None):
    app = Flask(__name__)
    app.config["DATABASE"] = os.environ.get("ACEEST_DB", "aceest_fitness.db")
    app.config.update(config or {})

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        get_db().executescript(SCHEMA)

    # ---- error handling ---------------------------------------------------
    @app.errorhandler(ValidationError)
    def handle_validation(err):
        return jsonify(error=str(err)), 400

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
            "SELECT name, age, weight_kg, program, calories "
            "FROM clients WHERE name = ?", (name,)
        ).fetchone()

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
            "SELECT name, age, weight_kg, program, calories "
            "FROM clients ORDER BY name"
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/clients")
    def create_client():
        client = validate_client(json_body())
        db = get_db()
        try:
            db.execute(
                "INSERT INTO clients (name, age, weight_kg, program, calories)"
                " VALUES (:name, :age, :weight_kg, :program, :calories)",
                client,
            )
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify(
                error=f"client '{client['name']}' already exists"
            ), 409
        return jsonify(client), 201

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

    return app


if __name__ == "__main__":
    create_app().run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
    )
