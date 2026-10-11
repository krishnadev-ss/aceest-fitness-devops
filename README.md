# ACEest Fitness & Gym — Flask service with automated CI/CD

[![CI/CD Pipeline](https://github.com/krishnadev-ss/aceest-fitness-devops/actions/workflows/main.yml/badge.svg)](https://github.com/krishnadev-ss/aceest-fitness-devops/actions/workflows/main.yml)

A small Flask web application for gym management (training programs, calorie
and BMI calculators, client records and weekly adherence tracking), delivered
with a complete DevOps workflow: Git branching, Pytest, Docker, a Jenkins
build job and a GitHub Actions pipeline.

*Introduction to DevOps (CSIZG514 / SEZG514) — Assignment 1.*

## Contents

| Path | Purpose |
|------|---------|
| `app.py` | Flask application (app factory, business logic, SQLite storage) |
| `legacy/` | The ten baseline ACEest desktop scripts (v1.0 → v3.2.4), unchanged |
| `requirements.txt` | Runtime dependencies (Flask, gunicorn) |
| `requirements-dev.txt` | Runtime + test/lint tooling (pytest, pytest-cov, flake8) |
| `tests/` | Pytest suite: `test_logic.py` (unit), `test_api.py` (HTTP endpoints), `test_features.py` (v2.2.4 – v3.2.4 features), `test_ui.py` (web pages) |
| `Dockerfile` | Multi-stage image: `test` target and non-root `runtime` target |
| `Jenkinsfile` | Jenkins declarative pipeline (clean build + quality gate) |
| `.github/workflows/main.yml` | GitHub Actions pipeline |
| `docs/VM_RUNBOOK.md` | Step-by-step guide for running everything on a fresh Linux VM |

## Application overview

The baseline ACEest scripts were Tkinter desktop programs, delivered in ten
versions (v1.0 → v3.2.4, kept unchanged in [`legacy/`](legacy)). Their logic is
exposed here as a web service: the three training programs, the calorie formula
(`weight_kg × program factor`), BMI, client profiles and goals, weekly
adherence, workout and exercise logging, body metrics, membership tracking, the
program generator, client reports, CSV export and role-based login.

| Baseline version | Feature | Endpoint(s) |
|------------------|---------|-------------|
| v1.0 – v1.1 | Programs, calorie estimate, save client | `/api/programs`, `/api/calories`, `/api/clients` |
| v1.1.2 | CSV export, progress chart | `/api/export/clients.csv`, `/api/clients/<name>/progress` |
| v2.0.1 – v2.2.1 | SQLite clients + weekly adherence | `/api/clients/<name>/progress` |
| v2.2.4 – v3.0.1 | Height / goals, BMI, workouts + exercises, body metrics, weight trend | `PATCH /api/clients/<name>`, `/api/bmi`, `/workouts`, `/metrics` |
| v3.1.2 | Login with roles, program generator, PDF report | `/api/login`, `/api/users`, `/program/generate`, `/report` |
| v3.2.4 | Membership status and renewal date | `/api/clients/<name>/membership` |

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard: client list (BMI, plan, membership), totals and programs |
| GET | `/clients/<name>` | Web page for one client: profile, goals, membership, adherence and weight charts, workouts, body metrics |
| GET | `/health` | Liveness probe (`{"status": "ok"}`) |
| GET | `/api/metrics` | Gym capacity, area and break-even figures |
| GET | `/api/programs` | All programs (`FL`, `MG`, `BG`) |
| GET | `/api/programs/<code>` | One program's workout and diet plan |
| POST | `/api/calories` | Body `{"weight_kg", "program"}` → daily calorie estimate |
| POST | `/api/bmi` | Body `{"weight_kg", "height_cm"}` → BMI and category |
| GET / POST | `/api/clients` | List clients / create one (`name`, `age`, `weight_kg`, `program`; optional `height_cm`, `target_weight`, `target_adherence`, `membership_end`) |
| GET / PATCH / DELETE | `/api/clients/<name>` | Fetch, update (calories recomputed) or remove a client |
| GET / POST | `/api/clients/<name>/progress` | Adherence history / log a week (`adherence` 0–100, optional `week`) |
| GET / POST | `/api/clients/<name>/workouts` | Workout history / log a session (`workout_type` Strength, Hypertrophy, Cardio or Mobility; `duration_min`, `date`, `notes`, `exercises[]` with `name`, `sets`, `reps`, `weight_kg`) |
| GET / POST | `/api/clients/<name>/metrics` | Body metrics and weight trend / log `weight_kg`, `waist_cm`, `bodyfat` |
| GET / PUT | `/api/clients/<name>/membership` | Membership status, end date and days remaining / update them |
| POST | `/api/clients/<name>/program/generate` | Pick a training plan for the client's program (optional `seed`) |
| GET | `/api/clients/<name>/report` | Full client report (profile, BMI, goals, adherence, workouts, last metrics, membership) |
| GET | `/api/export/clients.csv` | All clients as CSV |
| POST | `/api/login` | Check `username` / `password`, returns the role |
| POST | `/api/users` | Create a user (`role` Admin, Trainer or Member) |

Invalid input returns `400` with `{"error": "..."}`; unknown resources return
`404`; a duplicate client or user returns `409`; a failed login returns `401`.
A default `admin` user is created on first start; its password comes from
`ACEEST_ADMIN_PASSWORD` (default `admin`, change it outside a lab). Passwords
are stored as salted hashes. Databases created by v1.0.0 are upgraded in place.

## Local setup and execution

Requirements: Python 3.9+ and Git. Docker is only needed for the container steps.

```bash
git clone https://github.com/krishnadev-ss/aceest-fitness-devops.git
cd aceest-fitness-devops

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python app.py                        # http://127.0.0.1:5000
```

Try it:

```bash
curl http://127.0.0.1:5000/health
curl -X POST http://127.0.0.1:5000/api/calories \
     -H "Content-Type: application/json" \
     -d '{"weight_kg": 70, "program": "FL"}'
```

Configuration is by environment variable: `ACEEST_DB` (SQLite file path,
default `aceest_fitness.db`), `HOST` and `PORT` (development server only).

### Run with Docker

```bash
docker build -t aceest-fitness .
docker run --rm -p 5000:5000 aceest-fitness
```

The runtime image is based on `python:3.12-slim`, contains no test tooling,
runs gunicorn as an unprivileged user (UID 10001) and has a `HEALTHCHECK`
on `/health`. To keep client data between runs, mount a volume:
`-v aceest-data:/app/data`.

## Running the tests manually

```bash
# in the virtual environment
flake8 .                                   # lint
pytest                                     # full suite
pytest --cov=app --cov-report=term-missing # with coverage
pytest tests/test_logic.py -k bmi          # a subset
```

Inside the container (exactly what CI does):

```bash
docker build --target test -t aceest-fitness:test .
docker run --rm aceest-fitness:test
```

Each test gets its own temporary SQLite database, so tests are independent
and leave nothing behind.

## CI/CD integration

```
 developer ──git push──▶ GitHub ──┬──▶ GitHub Actions  (every push / pull request)
                                  │      1. Build & Lint
                                  │      2. Docker Image Assembly
                                  │      3. Automated Testing in the container
                                  │
                                  └──▶ Jenkins  (polls the repository)
                                         Checkout → Clean Build → Compile & Lint
                                         → Unit Tests → Docker Build & Test
```

### GitHub Actions (`.github/workflows/main.yml`)

Triggered on every `push` and `pull_request`. Three jobs run in sequence, each
gated on the previous one with `needs`:

1. **Build & Lint** — installs dependencies, byte-compiles the sources
   (`python -m compileall`) to catch syntax errors, then runs `flake8`.
2. **Docker Image Assembly** — builds the runtime image and smoke-tests it by
   starting a container and polling `/health`.
3. **Automated Testing** — builds the `test` stage of the Dockerfile and runs
   the Pytest suite *inside* that container.

A failure in any stage stops the pipeline and marks the commit as failed.

### Jenkins (`Jenkinsfile`)

Jenkins is the secondary, controlled BUILD environment. A Pipeline job
configured as *Pipeline script from SCM* points at this repository and runs
the `Jenkinsfile`:

1. **Checkout** — wipes the workspace and pulls the latest commit from GitHub.
2. **Clean Build** — creates a brand-new virtual environment and installs
   pinned dependencies, so nothing is reused from earlier builds.
3. **Compile & Lint** — `py_compile` + `flake8`.
4. **Unit Tests** — Pytest with a JUnit report and a 90 % coverage gate.
5. **Docker Build & Test** — builds the image and runs the tests in the
   container (skipped automatically if the Jenkins user cannot reach the Docker daemon).

The job polls GitHub every five minutes (`pollSCM`), so a push triggers a build
without needing a publicly reachable webhook. Setup steps are in
[`docs/VM_RUNBOOK.md`](docs/VM_RUNBOOK.md).

## Version control strategy

- `main` — always releasable; only receives merges from `develop`.
- `develop` — integration branch.
- `feature/*`, `ci/*`, `docs/*` — one short-lived branch per unit of work,
  merged with `--no-ff` so the history shows each change as a group.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `test:`, `build:`, `ci:`, `docs:`); releases are tagged (`v1.0.0`,
  `v2.0.0`).
- Each baseline script was committed into `legacy/` in order and tagged
  `baseline-v1.0` … `baseline-v3.2.4`, so `git log -- legacy/` shows how the
  original program evolved.

## Execution evidence (screenshots)

All screenshots live in [`docs/screenshots/`](docs/screenshots); the raw
terminal output behind the local-run screenshots is kept in
[`docs/evidence/`](docs/evidence).

### 1. Version control (GitHub)

| Repository | Branches |
|---|---|
| ![Repository](docs/screenshots/01-github-repository.png) | ![Branches](docs/screenshots/02-github-branches.png) |

| Commit history on `main` | Branch graph (`git log --graph`) |
|---|---|
| ![Commits](docs/screenshots/03-github-commit-history.png) | ![Git graph](docs/screenshots/06-git-branch-history.png) |

### 2. Application and unit tests (local run)

Compile check and flake8 — no issues:

![Compile and lint](docs/screenshots/07-local-compile-and-lint.png)

Pytest — **95 passed, 99 % coverage of `app.py`**:

![Pytest](docs/screenshots/08-local-pytest-passed.png)

Flask service answering real requests (client with goals, weekly progress,
workout with exercises, body metrics, membership, program generator, login):

![API calls](docs/screenshots/09-local-flask-api-calls.png)

Client report (BMI, goals, adherence, workouts, last metrics, membership) and
CSV export:

![Report and CSV](docs/screenshots/09b-local-client-report-and-csv.png)

Web dashboard at `http://127.0.0.1:5000/`: totals, every client with BMI,
generated plan and membership status (Active / Paused / Expired), and the
program catalogue:

![Dashboard](docs/screenshots/10-ui-dashboard.png)

Client page `/clients/Ravi`: profile, membership, goals, weekly-adherence and
weight-trend charts (target shown dashed), workouts with exercises and body
metrics:

![Client page - Ravi](docs/screenshots/10b-ui-client-ravi.png)

A second client (`/clients/Asha`, Fat Loss program):

![Client page - Asha](docs/screenshots/10c-ui-client-asha.png)

### 3. GitHub Actions CI/CD

Every push triggers the *CI/CD Pipeline* workflow; all runs are green:

![Actions runs](docs/screenshots/04-github-actions-runs.png)

Run on `main`: Build & Lint → Docker Image Assembly → Automated Testing (in container), all successful:

![Pipeline graph](docs/screenshots/05-github-actions-pipeline-success.png)

### 4. Docker on the lab VM (BITS Prayogshala)

| Image build (126 MB) | Pytest inside the container: 51 passed |
|---|---|
| ![Docker build](docs/screenshots/11-vm-docker-build.png) | ![Tests in container](docs/screenshots/12-vm-docker-tests-in-container.png) |

Container running, `/health` OK, status `healthy`, non-root user `aceest`:

![Container healthy](docs/screenshots/13-vm-docker-run-healthy.png)

Latest code pulled on the VM: ![git pull](docs/screenshots/14-vm-git-pull.png)

### 5. Jenkins BUILD on the lab VM

Pipeline job `aceest-fitness-build`: Pipeline script from SCM, this repository, branch `*/main`, script path `Jenkinsfile`.

| Stage view: all stages green | Job page and test trend |
|---|---|
| ![Stages](docs/screenshots/15-vm-jenkins-pipeline-stages.png) | ![Job](docs/screenshots/16-vm-jenkins-job-builds.png) |

| Test results: 51 passing | Console: Finished: SUCCESS |
|---|---|
| ![Tests](docs/screenshots/17-vm-jenkins-test-results.png) | ![Console](docs/screenshots/19-vm-jenkins-console-success.png) |
