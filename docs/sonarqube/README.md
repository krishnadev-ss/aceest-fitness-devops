# SonarQube report - ACEest Fitness & Gym v3.0.0

Source: SonarQube 9.9.3 LTS on the lab VM, project key `aceest-fitness`, analysed by
Jenkins job `aceest-fitness-cicd` (build #3, v3.0.0) with `sonar.qualitygate.wait=true`.

| Measure (overall code) | Value |
| --- | --- |
| Quality gate | **Passed** (all conditions OK) |
| Bugs | 0 |
| Vulnerabilities | 0 |
| Security hotspots | 1 |
| Code smells | 1 |
| Technical debt | 1 h 15 min |
| Coverage | 99.1 % |
| Unit tests | 103 passed |

Files in this folder (from the Jenkins build artefacts):

- `sonarqube-quality-gate.json` - quality gate status returned by the SonarQube API
- `coverage.xml` - Cobertura coverage report read by SonarQube
- `pytest.xml` - JUnit test report read by SonarQube and Jenkins
