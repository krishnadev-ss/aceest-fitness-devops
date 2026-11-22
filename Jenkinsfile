// ACEest Fitness & Gym - Jenkins CI/CD pipeline (Assignment 2).
//
//   Checkout -> Clean Build -> Lint -> Unit Tests -> SonarQube + Quality Gate
//   -> Docker Build -> Tests in Container -> Push to Docker Hub
//   -> Deploy to Kubernetes (rolling, blue-green, canary, A/B, shadow)
//      with in-cluster Pytest smoke tests and automatic rollback.
//
// Jenkins credentials used (Manage Jenkins -> Credentials):
//   dockerhub-creds   Username with password   Docker Hub user + access token
//                     (optional: without it the agent's own `docker login` and
//                      the DOCKERHUB_USER parameter are used)
//   sonarqube-token   Secret text              SonarQube user token
// The agent needs docker, kubectl (with a kubeconfig for the cluster) and
// python3. Stages whose tools/credentials are missing are skipped, not failed.
pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 40, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20', artifactNumToKeepStr: '10'))
        disableConcurrentBuilds()
    }

    triggers {
        // Poll GitHub every ~2 minutes; a new commit starts a build.
        pollSCM('H/2 * * * *')
    }

    parameters {
        choice(name: 'STRATEGY',
               choices: ['all', 'rolling', 'bluegreen', 'canary', 'ab', 'shadow', 'none'],
               description: 'Deployment strategy to release this build with')
        booleanParam(name: 'PROMOTE_CANARY', defaultValue: false,
               description: 'After a healthy canary, promote it to the stable pods')
        string(name: 'SONAR_HOST_URL', defaultValue: 'http://localhost:9000',
               description: 'SonarQube server')
        string(name: 'DOCKERHUB_USER', defaultValue: 'krishnadevss',
               description: 'Docker Hub account (used when the agent is already docker-logged-in)')
    }

    environment {
        VENV       = '.venv'
        IMAGE_NAME = 'aceest-fitness'
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                script {
                    env.APP_VERSION = sh(returnStdout: true,
                        script: "sed -n 's/^APP_VERSION = \"\\(.*\\)\"/\\1/p' app.py").trim()
                    env.GIT_SHORT = sh(returnStdout: true,
                        script: 'git rev-parse --short HEAD').trim()
                    env.BUILD_TAG_IMG = "${env.APP_VERSION}-b${env.BUILD_NUMBER}"
                    currentBuild.displayName = "#${env.BUILD_NUMBER} v${env.APP_VERSION} (${env.GIT_SHORT})"
                }
                echo "Building ACEest v${env.APP_VERSION} commit ${env.GIT_SHORT}"
            }
        }

        stage('Clean Build') {
            steps {
                sh '''
                    python3 -m venv "$VENV"
                    "$VENV/bin/pip" install -q --upgrade pip
                    "$VENV/bin/pip" install -q -r requirements-dev.txt
                '''
            }
        }

        stage('Compile & Lint') {
            steps {
                sh '''
                    "$VENV/bin/python" -m py_compile app.py
                    "$VENV/bin/flake8" .
                '''
            }
        }

        stage('Unit Tests') {
            steps {
                sh '''
                    mkdir -p reports
                    "$VENV/bin/pytest" --junitxml=reports/pytest.xml \
                        --cov=app --cov-report=term-missing \
                        --cov-report=xml:reports/coverage.xml \
                        --cov-report=html:reports/coverage-html \
                        --cov-fail-under=90
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/pytest.xml'
                }
            }
        }

        stage('SonarQube Analysis') {
            when { expression { hasCredential('sonarqube-token') && dockerOk() } }
            steps {
                withCredentials([string(credentialsId: 'sonarqube-token', variable: 'SONAR_TOKEN')]) {
                    // sonar.qualitygate.wait=true (sonar-project.properties):
                    // the scanner waits for the Quality Gate and fails the build if it fails.
                    sh '''
                        docker run --rm --network host -u "$(id -u):$(id -g)" \
                            -e SONAR_HOST_URL="$SONAR_HOST_URL" -e SONAR_TOKEN \
                            -e SONAR_USER_HOME=/usr/src/.sonar \
                            -v "$WORKSPACE:/usr/src" \
                            sonarsource/sonar-scanner-cli:5.0.1 \
                            -Dsonar.projectVersion="$APP_VERSION" \
                            -Dsonar.scm.revision="$GIT_COMMIT"
                    '''
                }
                // Keep the quality-gate result with the build.
                withCredentials([string(credentialsId: 'sonarqube-token', variable: 'SONAR_TOKEN')]) {
                    sh '''
                        curl -sf -u "$SONAR_TOKEN:" \
                          "$SONAR_HOST_URL/api/qualitygates/project_status?projectKey=aceest-fitness" \
                          -o reports/sonarqube-quality-gate.json || echo "gate status not available"
                        curl -sf -u "$SONAR_TOKEN:" \
                          "$SONAR_HOST_URL/api/measures/component?component=aceest-fitness&metricKeys=bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,ncloc,sqale_rating,reliability_rating,security_rating" \
                          -o reports/sonarqube-measures.json || echo "measures not available"
                        cat reports/sonarqube-quality-gate.json; echo
                    '''
                }
            }
        }

        stage('Docker Build') {
            when { expression { dockerOk() } }
            steps {
                sh '''
                    docker build \
                        --build-arg APP_VERSION="$APP_VERSION" --build-arg GIT_COMMIT="$GIT_COMMIT" \
                        -t "$IMAGE_NAME:$BUILD_TAG_IMG" .
                    docker build --target test \
                        --build-arg APP_VERSION="$APP_VERSION" --build-arg GIT_COMMIT="$GIT_COMMIT" \
                        -t "$IMAGE_NAME:$BUILD_TAG_IMG-test" .
                    docker image ls "$IMAGE_NAME"
                '''
            }
        }

        stage('Tests in Container') {
            when { expression { dockerOk() } }
            steps {
                sh '''
                    # 1) full Pytest suite inside the test image
                    docker run --rm "$IMAGE_NAME:$BUILD_TAG_IMG-test"

                    # 2) start the runtime image and run the smoke suite against it
                    docker rm -f "aceest-ci-$BUILD_NUMBER" >/dev/null 2>&1 || true
                    docker run -d --name "aceest-ci-$BUILD_NUMBER" "$IMAGE_NAME:$BUILD_TAG_IMG"
                    docker run --rm --network "container:aceest-ci-$BUILD_NUMBER" \
                        -e BASE_URL=http://127.0.0.1:5000 -e EXPECTED_VERSION="$APP_VERSION" \
                        "$IMAGE_NAME:$BUILD_TAG_IMG-test" pytest smoke -v -p no:cacheprovider
                '''
            }
            post {
                always { sh 'docker rm -f "aceest-ci-$BUILD_NUMBER" >/dev/null 2>&1 || true' }
            }
        }

        stage('Push to Docker Hub') {
            when { expression { dockerOk() && (hasCredential('dockerhub-creds') || dockerLoggedIn()) } }
            steps {
                script {
                    if (hasCredential('dockerhub-creds')) {
                        withCredentials([usernamePassword(credentialsId: 'dockerhub-creds',
                                usernameVariable: 'DH_USER', passwordVariable: 'DH_TOKEN')]) {
                            sh 'echo "$DH_TOKEN" | docker login -u "$DH_USER" --password-stdin'
                            pushImages(env.DH_USER)
                        }
                    } else {
                        // The agent's Docker client is already signed in (docker login).
                        pushImages(params.DOCKERHUB_USER)
                    }
                    env.IMAGE_REPO = readFile('reports/image-repo.txt').trim()
                }
            }
        }

        stage('Deploy to Kubernetes') {
            when {
                expression {
                    params.STRATEGY != 'none' && env.IMAGE_REPO &&
                    sh(script: 'kubectl get nodes >/dev/null 2>&1', returnStatus: true) == 0
                }
            }
            steps {
                // scripts/k8s.sh tests every step with an in-cluster Pytest Job
                // and rolls back automatically when a check fails.
                sh 'scripts/k8s.sh release "$BUILD_TAG_IMG" "$STRATEGY"'
                script {
                    if (params.PROMOTE_CANARY && params.STRATEGY in ['all', 'canary']) {
                        sh 'CURRENT_TAG="$BUILD_TAG_IMG" scripts/k8s.sh canary-promote'
                    }
                }
            }
            post {
                always {
                    sh '''
                        mkdir -p reports
                        scripts/k8s.sh status > reports/k8s-status.txt 2>&1 || true
                        scripts/k8s.sh urls  >> reports/k8s-status.txt 2>&1 || true
                        kubectl -n aceest get deploy,rs,svc,pods,jobs -o wide >> reports/k8s-status.txt 2>&1 || true
                    '''
                }
            }
        }

        stage('Build Artifact') {
            steps {
                sh '''
                    mkdir -p dist
                    cat > reports/build-info.json <<EOF
{"app": "aceest-fitness", "version": "$APP_VERSION", "build": "$BUILD_NUMBER",
 "image_tag": "$BUILD_TAG_IMG", "image_repo": "${IMAGE_REPO:-local}",
 "commit": "$GIT_COMMIT", "branch": "${GIT_BRANCH:-}", "built_at": "$(date -u +%FT%TZ)"}
EOF
                    tar czf "dist/aceest-fitness-$BUILD_TAG_IMG.tar.gz" \
                        app.py requirements.txt Dockerfile k8s scripts reports/build-info.json
                '''
                archiveArtifacts artifacts: 'dist/*.tar.gz, reports/**', fingerprint: true,
                                 allowEmptyArchive: true
            }
        }
    }

    post {
        success { echo "PIPELINE OK - v${env.APP_VERSION} image tag ${env.BUILD_TAG_IMG}" }
        failure { echo 'PIPELINE FAILED - see the failing stage; deployments were rolled back by scripts/k8s.sh' }
    }
}

// --- helpers -----------------------------------------------------------------
def dockerOk() {
    return sh(script: 'docker info > /dev/null 2>&1', returnStatus: true) == 0
}

def dockerLoggedIn() {
    return sh(script: 'grep -q index.docker.io "$HOME/.docker/config.json" 2>/dev/null',
              returnStatus: true) == 0
}

def pushImages(String user) {
    withEnv(["DH_USER=${user}"]) {
        sh '''
            REPO="docker.io/$DH_USER/$IMAGE_NAME"
            for t in "$BUILD_TAG_IMG" "$APP_VERSION" "$GIT_SHORT" latest; do
                docker tag "$IMAGE_NAME:$BUILD_TAG_IMG" "$REPO:$t"
                docker push -q "$REPO:$t"
            done
            for t in "$BUILD_TAG_IMG-test" "$APP_VERSION-test" latest-test; do
                docker tag "$IMAGE_NAME:$BUILD_TAG_IMG-test" "$REPO:$t"
                docker push -q "$REPO:$t"
            done
            mkdir -p reports && echo "$REPO" > reports/image-repo.txt
        '''
    }
}

def hasCredential(String id) {
    try {
        withCredentials([string(credentialsId: id, variable: 'X')]) { }
        return true
    } catch (ignored) {
        try {
            withCredentials([usernamePassword(credentialsId: id,
                    usernameVariable: 'U', passwordVariable: 'P')]) { }
            return true
        } catch (ignored2) {
            echo "Credential '${id}' not configured - skipping the stage that needs it"
            return false
        }
    }
}
