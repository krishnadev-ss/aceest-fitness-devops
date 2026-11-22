# Assignment 2 — CI/CD pipeline with SonarQube, Docker Hub and Kubernetes

Continuation of Assignment 1. The same Flask application (now **v3.0.0**) is
taken from a Git commit all the way to five Kubernetes deployment strategies,
with tests and a quality gate in front of every step and an automatic rollback
behind it.

## 1. Architecture

```
developer ──git push──▶ GitHub (main / develop / feature/* ; tags v1.0.0 … v3.0.0)
                           │
                           ├──▶ GitHub Actions (every push/PR): lint → image → tests in container
                           │
                           └──▶ Jenkins (pollSCM every 2 min, Jenkinsfile)
                                 1 Checkout            git, version + commit → build name
                                 2 Clean Build         fresh venv
                                 3 Compile & Lint      py_compile, flake8
                                 4 Unit Tests          pytest, JUnit, coverage ≥ 90 % (xml + html)
                                 5 SonarQube           sonar-scanner → Quality Gate (build fails if red)
                                 6 Docker Build        runtime + test images, OCI labels
                                 7 Tests in Container  full suite in test image; smoke suite vs running image
                                 8 Push to Docker Hub  <user>/aceest-fitness:{3.0.0-bN, 3.0.0, sha, latest}
                                 9 Deploy to K8s       scripts/k8s.sh release (all 5 strategies)
                                                       each step: rollout → in-cluster Pytest Job → rollback on failure
                                10 Build Artifact      dist/aceest-fitness-<ver>-b<N>.tar.gz + reports archived
                           Minikube cluster, namespace "aceest"
   ┌──────────────┬──────────────────┬──────────────────┬───────────────────┬──────────────────┐
   │ Rolling      │ Blue-Green       │ Canary           │ A/B testing       │ Shadow           │
   │ :30080       │ live :30081      │ :30082           │ router :30083     │ router :30084    │
   │ 3 pods,      │ preview :30085   │ stable×3 +       │ NGINX: header/    │ NGINX mirrors    │
   │ surge 1,     │ selector switch  │ canary×1 (~25 %) │ cookie/50-50 hash │ every request to │
   │ unavailable 0│ blue ⇄ green     │ promote/rollback │ variant A | B     │ shadow, discards │
   └──────────────┴──────────────────┴──────────────────┴───────────────────┴──────────────────┘
```

Every pod sets `DEPLOY_TRACK` (blue, green, stable, canary, variant-a,
variant-b, live, shadow). v3.0.0 returns it from `/version`, `/health`, in the
page header and in the `X-App-Version`, `X-Deploy-Track` and `X-Served-By`
response headers, so you can see which release and which pod answered.

## 2. What changed in v3.0.0

| Area | Change |
|------|--------|
| App | `/version`, `/ready` (DB check), release headers on every response, track badge in the UI, gunicorn access log |
| Tests | `tests/test_release.py` (8 unit tests); `smoke/test_deployment.py` (6 post-deployment tests, run against a URL) |
| Quality | `sonar-project.properties`, `.coveragerc` (relative paths for SonarQube) |
| Image | OCI labels (version, commit), smoke suite inside the test image |
| Jenkins | SonarQube + quality gate, container tests, Docker Hub push, Kubernetes deploy with rollback, build artifacts |
| Kubernetes | `k8s/` manifests for the five strategies, `scripts/k8s.sh` to drive them |
| Registry | `scripts/publish-all-versions.sh` pushes every tagged version (1.0.0 … 3.0.0) |

## 3. Running it on the lab VM (Rocky Linux 9, BITS Prayogshala)

### 3.1 One-time setup

```bash
# kubectl + Minikube
cd /tmp
curl -sLO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -m 755 kubectl /usr/local/bin/kubectl
curl -sLO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install -m 755 minikube-linux-amd64 /usr/local/bin/minikube
sudo ln -sf /usr/local/bin/kubectl /usr/bin/kubectl     # visible to the jenkins user
minikube start --driver=docker --cpus=2 --memory=3072

# Jenkins (system service) needs Docker and the cluster
sudo usermod -aG docker jenkins
sudo mkdir -p /var/lib/jenkins/.kube
kubectl config view --flatten --minify | sudo tee /var/lib/jenkins/.kube/config >/dev/null
sudo chown -R jenkins:jenkins /var/lib/jenkins/.kube && sudo chmod 600 /var/lib/jenkins/.kube/config
sudo systemctl restart jenkins

# SonarQube 9.9 LTS (pre-installed in /opt/sonarqube) needs Java 17, not 21
sudo mkdir -p /etc/systemd/system/sonarqube.service.d
printf '[Service]\nEnvironment=SONAR_JAVA_PATH=/usr/lib/jvm/java-17-openjdk/bin/java\n' \
  | sudo tee /etc/systemd/system/sonarqube.service.d/java17.conf
echo 'vm.max_map_count=524288' | sudo tee /etc/sysctl.d/99-sonarqube.conf && sudo sysctl --system
sudo systemctl daemon-reload && sudo systemctl restart sonarqube
curl -s localhost:9000/api/system/status        # {"status":"UP"} after ~1 min
```

### 3.2 Credentials (you enter these yourself)

1. **SonarQube** — open `http://localhost:9000`, log in, change the default
   password, then *My Account → Security → Generate token* (type *Global
   analysis token* or *User token*).
2. **Docker Hub** — hub.docker.com → *Account settings → Personal access
   tokens* → new token with *Read & Write*.
3. **Jenkins** — *Manage Jenkins → Credentials → System → Global → Add*:
   - `dockerhub-creds`: *Username with password* (Docker Hub user + token)
   - `sonarqube-token`: *Secret text* (the SonarQube token)

### 3.3 Publish every version to Docker Hub

```bash
cd ~/workspace/aceest-fitness-devops
docker login -u <dockerhub-user>                 # paste the access token
DOCKERHUB_USER=<dockerhub-user> scripts/publish-all-versions.sh
```

Result: `<user>/aceest-fitness:1.0.0, 2.0.0, 2.0.1, 2.0.2, 2.1.0, 3.0.0, latest`
(+ `-test` images with the Pytest suite).

### 3.4 Jenkins job

Job `aceest-fitness-cicd` → *Pipeline* → *Pipeline script from SCM* → Git
`https://github.com/krishnadev-ss/aceest-fitness-devops.git`, branch `*/main`,
script path `Jenkinsfile`. *Build Now* once (the first run registers the
parameters and the poll trigger); afterwards every push to `main` is picked up
within ~2 minutes.

### 3.5 Kubernetes by hand

```bash
export IMAGE_REPO=docker.io/<dockerhub-user>/aceest-fitness
scripts/k8s.sh init                  # all strategies: stable=2.1.0, new=3.0.0
scripts/k8s.sh release 3.0.0 all     # progressive release with smoke tests
scripts/k8s.sh urls                  # NodePort URLs (open in the VM browser)
scripts/k8s.sh status
```

| Strategy | Try it | Roll back |
|----------|--------|-----------|
| Rolling | `scripts/k8s.sh rolling 3.0.0` — watch `kubectl -n aceest get pods -w` | `scripts/k8s.sh rolling-rollback` (`kubectl rollout undo`) |
| Blue-Green | `scripts/k8s.sh bluegreen 3.0.0` — idle colour is tested on :30085 before the switch | `scripts/k8s.sh bluegreen-rollback` (instant selector switch) |
| Canary | `scripts/k8s.sh canary 3.0.0`; `for i in $(seq 20); do curl -s $URL/version; echo; done` | `scripts/k8s.sh canary-rollback` / `canary-promote` |
| A/B | `curl -H 'X-Variant: b' $URL/version`; browsers get a sticky `variant` cookie | `scripts/k8s.sh ab 2.1.0` |
| Shadow | `curl $URL/version` (always live) then `kubectl -n aceest logs deploy/aceest-shadow` | `scripts/k8s.sh shadow 2.1.0` |

Automatic rollback demo (a tag that does not exist never becomes ready):

```bash
ROLLOUT_TIMEOUT=60s scripts/k8s.sh rolling 9.9.9-broken   # → "rolling back to …"
```

To reach the services from outside the VM: `scripts/k8s.sh expose`
(port-forwards on the VM address, ports 8081–8086).
