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
| `requirements.txt` | Runtime dependencies (Flask, gunicorn) |
| `requirements-dev.txt` | Runtime + test/lint tooling (pytest, pytest-cov, flake8) |
| `tests/` | Pytest suite: `test_logic.py` (unit), `test_api.py` (HTTP endpoints) |
| `Dockerfile` | Multi-stage image: `test` target and non-root `runtime` target |
| `Jenkinsfile` | Jenkins declarative pipeline (clean build + quality gate) |
| `.github/workflows/main.yml` | GitHub Actions pipeline |
| `docs/VM_RUNBOOK.md` | Step-by-step guide for running everything on a fresh Linux VM |

## Application overview

The baseline ACEest script was a Tkinter desktop program. Its core logic — the
three training programs, the calorie formula (`weight_kg × program factor`),
client records and weekly adherence — is exposed here as a web service.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | HTML overview page of all programs |
| GET | `/health` | Liveness probe (`{"status": "ok"}`) |
| GET | `/api/metrics` | Gym capacity, area and break-even figures |
| GET | `/api/programs` | All programs (`FL`, `MG`, `BG`) |
| GET | `/api/programs/<code>` | One program's workout and diet plan |
| POST | `/api/calories` | Body `{"weight_kg", "program"}` → daily calorie estimate |
| POST | `/api/bmi` | Body `{"weight_kg", "height_cm"}` → BMI and category |
| GET / POST | `/api/clients` | List clients / create one (`name`, `age`, `weight_kg`, `program`) |
| GET / DELETE | `/api/clients/<name>` | Fetch or remove a client |
| GET / POST | `/api/clients/<name>/progress` | Adherence history / log a week (`adherence` 0–100, optional `week`) |

Invalid input returns `400` with `{"error": "..."}`; unknown resources return
`404`; a duplicate client name returns `409`.

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
  (`feat:`, `test:`, `build:`, `ci:`, `docs:`); releases are tagged (`v1.0.0`).
