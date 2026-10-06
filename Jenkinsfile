// ACEest Fitness & Gym - Jenkins BUILD & quality gate.
// Pulls the latest code from GitHub, rebuilds the environment from scratch,
// then lints, tests and (when Docker is present on the agent) builds the image.
pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 15, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
    }

    triggers {
        // Check GitHub for new commits every ~5 minutes.
        pollSCM('H/5 * * * *')
    }

    environment {
        VENV  = '.venv'
        IMAGE = "aceest-fitness:${env.BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
            }
        }

        stage('Clean Build') {
            steps {
                sh '''
                    python3 -m venv "$VENV"
                    "$VENV/bin/pip" install --upgrade pip
                    "$VENV/bin/pip" install -r requirements-dev.txt
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
                        --cov=app --cov-report=term-missing --cov-fail-under=90
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/pytest.xml'
                }
            }
        }

        stage('Docker Build & Test') {
            when {
                expression { sh(script: 'command -v docker', returnStatus: true) == 0 }
            }
            steps {
                sh '''
                    docker build -t "$IMAGE" .
                    docker build --target test -t "$IMAGE-test" .
                    docker run --rm "$IMAGE-test"
                '''
            }
        }
    }

    post {
        success { echo "BUILD OK - ${env.JOB_NAME} #${env.BUILD_NUMBER}" }
        failure { echo "BUILD FAILED - see the stage log above" }
    }
}
