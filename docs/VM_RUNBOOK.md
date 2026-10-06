# Runbook — running the project on a fresh Linux VM

Written for an Ubuntu/Debian lab VM (for example BITS Prayogshala). Run the
commands in order in the VM's terminal. Replace `<your-username>` with your
GitHub username.

## 0. See what the VM already has

```bash
python3 --version; git --version; docker --version; java -version
```

Skip any install step below for a tool that is already present.

## 1. Install the tools

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip curl

# Docker
sudo apt-get install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker                 # or log out and back in
docker run --rm hello-world   # confirms Docker works without sudo

# Java (needed by Jenkins)
sudo apt-get install -y fontconfig openjdk-21-jre
```

## 2. Get the code

```bash
cd ~
git clone https://github.com/<your-username>/aceest-fitness-devops.git
cd aceest-fitness-devops
```

## 3. Run the application and tests directly

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

flake8 .
pytest --cov=app --cov-report=term-missing     # expect: 51 passed

python app.py &                                # starts on port 5000
sleep 2
curl http://127.0.0.1:5000/health
curl http://127.0.0.1:5000/api/programs
curl -X POST http://127.0.0.1:5000/api/clients -H "Content-Type: application/json" \
     -d '{"name": "Ravi", "age": 28, "weight_kg": 80, "program": "MG"}'
curl http://127.0.0.1:5000/api/clients
kill %1                                        # stop the dev server
deactivate
```

## 4. Build and run with Docker

```bash
docker build -t aceest-fitness .
docker images aceest-fitness                   # note the image size

# tests inside the container
docker build --target test -t aceest-fitness:test .
docker run --rm aceest-fitness:test            # expect: 51 passed

# run the service
docker run -d --name aceest -p 5000:5000 aceest-fitness
sleep 3
curl http://127.0.0.1:5000/health
docker ps                                      # STATUS shows (healthy) after ~30 s
docker exec aceest whoami                      # aceest, not root
docker rm -f aceest
```

## 5. Jenkins

### 5.1 Start Jenkins

Running the WAR as your own user is the simplest option on a lab VM: the build
then has the same Python and Docker access you do.

```bash
mkdir -p ~/jenkins && cd ~/jenkins
curl -fLO https://get.jenkins.io/war-stable/latest/jenkins.war
nohup java -jar jenkins.war --httpPort=8080 > jenkins.log 2>&1 &
sleep 60
cat ~/.jenkins/secrets/initialAdminPassword
```

If port 8080 is taken, use another one (`--httpPort=9090`).

(If Jenkins is already installed as a service instead, give its user Docker
access: `sudo usermod -aG docker jenkins && sudo systemctl restart jenkins`.)

### 5.2 First-time setup

1. Open `http://localhost:8080` in the VM's browser (or `http://<vm-ip>:8080`).
2. Paste the initial admin password printed above.
3. Choose **Install suggested plugins** and wait for it to finish.
4. Create the admin user and accept the default URL.

### 5.3 Create the build job

1. **New Item** → name `aceest-fitness-build` → **Pipeline** → OK.
2. Under **Pipeline**:
   - Definition: **Pipeline script from SCM**
   - SCM: **Git**
   - Repository URL: `https://github.com/<your-username>/aceest-fitness-devops.git`
   - Credentials: none (the repository is public)
   - Branch Specifier: `*/main`
   - Script Path: `Jenkinsfile`
3. **Save** → **Build Now**.

### 5.4 Check the result

- The stage view should show Checkout, Clean Build, Compile & Lint,
  Unit Tests and Docker Build & Test all green.
- **Console Output** ends with `Finished: SUCCESS`.
- **Test Result** lists the 51 Pytest cases.

After this first build the job polls GitHub every five minutes, so pushing a
new commit starts a build automatically.

## 6. GitHub Actions

Nothing to install: open the repository on GitHub → **Actions** tab. Every push
and pull request runs *CI/CD Pipeline* with three jobs — Build & Lint, Docker
Image Assembly, Automated Testing (in container).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `permission denied ... docker.sock` | `sudo usermod -aG docker $USER`, then log out/in (restart Jenkins too) |
| `ensurepip is not available` | `sudo apt-get install -y python3-venv` |
| `Address already in use` on 5000 | `docker rm -f aceest` or run with `-p 5001:5000` |
| Jenkins skips the Docker stage | Docker is not on the PATH of the user running Jenkins |
| `docker build` cannot pull `python:3.12-slim` | The VM cannot reach Docker Hub — check the lab's proxy settings |
