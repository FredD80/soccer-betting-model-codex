# Phase 1 — Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Redis + Celery background worker infrastructure, K8s manifests for all 4 Phase 1 services (FastAPI, dashboard, Celery worker, Redis), activate the Ingress, update docker-compose for local dev, and extend the Jenkinsfile with new build stages.

**Architecture:** Redis is a ClusterIP-only broker (no external access). Celery worker shares the prediction engine codebase (different CMD). FastAPI and dashboard each have their own Deployment. Ingress routes `soccer.yourdomain.com/api/` to FastAPI and `soccer.yourdomain.com/` to the dashboard.

**Tech Stack:** Celery 5.x + redis Python client, Kubernetes 1.28+, nginx Ingress, MetalLB, Longhorn PVC.

**Can be executed in parallel with:** Phase 1 API & Dashboard plan.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `app/celery_app.py` | Celery app instance + task definitions |
| Create | `requirements.worker.txt` | Celery + redis deps |
| Modify | `requirements.txt` | Add celery + redis for scheduler runner |
| Create | `k8s/redis/deployment.yaml` | Redis pod |
| Create | `k8s/redis/service.yaml` | Redis ClusterIP service |
| Create | `k8s/celery-worker/deployment.yaml` | Celery worker pod |
| Create | `k8s/celery-worker/configmap.yaml` | Worker concurrency config |
| Create | `k8s/fastapi/deployment.yaml` | FastAPI pod |
| Create | `k8s/fastapi/service.yaml` | FastAPI ClusterIP service |
| Create | `k8s/dashboard/deployment.yaml` | nginx dashboard pod |
| Create | `k8s/dashboard/service.yaml` | Dashboard ClusterIP service |
| Modify | `k8s/ingress.yaml` | Activate routes for api/ and dashboard |
| Modify | `k8s/secret.yaml.example` | Add REDIS_URL and new API key placeholders |
| Modify | `k8s/configmap.yaml` | Add celery concurrency settings |
| Modify | `docker-compose.yaml` | Add redis, celery-worker, fastapi, dashboard services |
| Modify | `Jenkinsfile` | Add Build API, Build Worker, Build Dashboard stages |

---

## Task 1: Celery app + task definitions

**Files:**
- Create: `app/celery_app.py`
- Create: `requirements.worker.txt`
- Modify: `requirements.txt`

- [ ] **Step 1: Add celery and redis to requirements.txt**

Append to `requirements.txt`:

```
celery==5.4.0
redis==5.2.0
```

- [ ] **Step 2: Create requirements.worker.txt**

Same as requirements.txt but the worker doesn't need prometheus-client. For simplicity, workers use the same `requirements.txt` — no separate file needed. Skip this step.

- [ ] **Step 3: Write a failing test for Celery app import**

Create `tests/test_celery_app.py`:

```python
def test_celery_app_imports():
    from app.celery_app import celery_app
    assert celery_app.main == "app"


def test_task_names_registered():
    from app.celery_app import celery_app
    registered = set(celery_app.tasks.keys())
    assert "app.celery_app.form_cache_task" in registered
    assert "app.celery_app.spread_predict_task" in registered
    assert "app.celery_app.ou_analyze_task" in registered
```

- [ ] **Step 4: Run test to verify it fails**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
pip install celery redis
pytest tests/test_celery_app.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.celery_app'`

- [ ] **Step 5: Create app/celery_app.py**

```python
import logging
import os
from celery import Celery

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "app",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,           # re-queue on worker crash
    worker_prefetch_multiplier=1,  # one task at a time per worker (CPU-heavy tasks)
)


@celery_app.task(name="app.celery_app.form_cache_task")
def form_cache_task():
    """Rebuild form cache for all teams from completed results."""
    from app.db.connection import get_session
    from app.form_cache import FormCacheBuilder
    session = get_session()
    try:
        count = FormCacheBuilder(session).build_all()
        logger.info("form_cache_task: updated %d entries", count)
        return {"updated": count}
    finally:
        session.close()


@celery_app.task(name="app.celery_app.spread_predict_task")
def spread_predict_task():
    """Run spread predictor for upcoming fixtures."""
    from app.db.connection import get_session
    from app.db.models import ModelVersion
    from app.spread_predictor import SpreadPredictor
    from app.config import settings
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="spread_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="spread_v1", version=settings.spread_model_version,
                description="Phase 1 Poisson spread predictor", active=True,
            )
            session.add(mv)
            session.flush()
        SpreadPredictor(session).run(mv.id)
        session.commit()
        logger.info("spread_predict_task: complete")
        return {"status": "ok"}
    finally:
        session.close()


@celery_app.task(name="app.celery_app.ou_analyze_task")
def ou_analyze_task():
    """Run O/U analyzer for upcoming fixtures."""
    from app.db.connection import get_session
    from app.db.models import ModelVersion
    from app.ou_analyzer import OUAnalyzer
    from app.config import settings
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="ou_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="ou_v1", version=settings.ou_model_version,
                description="Phase 1 Poisson O/U analyzer", active=True,
            )
            session.add(mv)
            session.flush()
        OUAnalyzer(session).run(mv.id)
        session.commit()
        logger.info("ou_analyze_task: complete")
        return {"status": "ok"}
    finally:
        session.close()
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_celery_app.py -v
```

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app/celery_app.py requirements.txt tests/test_celery_app.py
git commit -m "feat: Celery app with form_cache, spread_predict, and ou_analyze tasks"
```

---

## Task 2: Redis K8s manifests

**Files:**
- Create: `k8s/redis/deployment.yaml`
- Create: `k8s/redis/service.yaml`

- [ ] **Step 1: Create k8s/redis/deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: tenant-b
  labels:
    app: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports:
            - containerPort: 6379
          command: ["redis-server", "--appendonly", "yes"]
          resources:
            requests:
              memory: "64Mi"
              cpu: "50m"
            limits:
              memory: "256Mi"
              cpu: "200m"
          volumeMounts:
            - name: redis-data
              mountPath: /data
      volumes:
        - name: redis-data
          persistentVolumeClaim:
            claimName: redis-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: redis-pvc
  namespace: tenant-b
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
```

- [ ] **Step 2: Create k8s/redis/service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: tenant-b
spec:
  selector:
    app: redis
  ports:
    - port: 6379
      targetPort: 6379
  type: ClusterIP
```

- [ ] **Step 3: Commit**

```bash
git add k8s/redis/
git commit -m "feat: Redis K8s deployment with Longhorn PVC and ClusterIP service"
```

---

## Task 3: Celery worker K8s manifests

**Files:**
- Create: `k8s/celery-worker/deployment.yaml`
- Create: `k8s/celery-worker/configmap.yaml`

- [ ] **Step 1: Create k8s/celery-worker/configmap.yaml**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: celery-worker-config
  namespace: tenant-b
data:
  CELERY_CONCURRENCY: "2"          # 2 concurrent tasks per worker pod
  CELERY_QUEUES: "default"
  # Red card normalization weights (used by FormCacheBuilder)
  RED_CARD_WEIGHT_BEFORE_60: "0.25"
  RED_CARD_WEIGHT_AFTER_60: "0.75"
```

- [ ] **Step 2: Create k8s/celery-worker/deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: celery-worker
  namespace: tenant-b
  labels:
    app: celery-worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: celery-worker
  template:
    metadata:
      labels:
        app: celery-worker
    spec:
      containers:
        - name: worker
          image: your-registry/soccer-betting-model:latest
          command:
            - celery
            - -A
            - app.celery_app
            - worker
            - --loglevel=info
            - --concurrency=$(CELERY_CONCURRENCY)
            - --queues=$(CELERY_QUEUES)
          envFrom:
            - secretRef:
                name: soccer-secrets
            - configMapRef:
                name: soccer-config
            - configMapRef:
                name: celery-worker-config
          resources:
            requests:
              memory: "256Mi"
              cpu: "200m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
```

- [ ] **Step 3: Commit**

```bash
git add k8s/celery-worker/
git commit -m "feat: Celery worker K8s deployment — 2 replicas, configurable concurrency"
```

---

## Task 4: FastAPI K8s manifests

**Files:**
- Create: `k8s/fastapi/deployment.yaml`
- Create: `k8s/fastapi/service.yaml`

- [ ] **Step 1: Create k8s/fastapi/deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi
  namespace: tenant-b
  labels:
    app: fastapi
spec:
  replicas: 1
  selector:
    matchLabels:
      app: fastapi
  template:
    metadata:
      labels:
        app: fastapi
    spec:
      containers:
        - name: api
          image: your-registry/soccer-api:latest
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: soccer-secrets
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

- [ ] **Step 2: Create k8s/fastapi/service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: fastapi
  namespace: tenant-b
spec:
  selector:
    app: fastapi
  ports:
    - port: 8000
      targetPort: 8000
  type: ClusterIP
```

- [ ] **Step 3: Commit**

```bash
git add k8s/fastapi/
git commit -m "feat: FastAPI K8s deployment and ClusterIP service"
```

---

## Task 5: Dashboard K8s manifests

**Files:**
- Create: `k8s/dashboard/deployment.yaml`
- Create: `k8s/dashboard/service.yaml`

- [ ] **Step 1: Create k8s/dashboard/deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dashboard
  namespace: tenant-b
  labels:
    app: dashboard
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dashboard
  template:
    metadata:
      labels:
        app: dashboard
    spec:
      containers:
        - name: dashboard
          image: your-registry/soccer-dashboard:latest
          ports:
            - containerPort: 80
          resources:
            requests:
              memory: "32Mi"
              cpu: "25m"
            limits:
              memory: "64Mi"
              cpu: "100m"
```

- [ ] **Step 2: Create k8s/dashboard/service.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: dashboard
  namespace: tenant-b
spec:
  selector:
    app: dashboard
  ports:
    - port: 80
      targetPort: 80
  type: ClusterIP
```

- [ ] **Step 3: Commit**

```bash
git add k8s/dashboard/
git commit -m "feat: Dashboard K8s deployment and ClusterIP service"
```

---

## Task 6: Activate K8s Ingress

**Files:**
- Modify: `k8s/ingress.yaml`

- [ ] **Step 1: Read the existing ingress.yaml**

```bash
cat /Users/fred/.claude/projects/soccer-betting-model/k8s/ingress.yaml
```

- [ ] **Step 2: Replace ingress.yaml with active routes**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: soccer-ingress
  namespace: tenant-b
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /$2
spec:
  ingressClassName: nginx
  rules:
    - host: soccer.yourdomain.com
      http:
        paths:
          # FastAPI — /api/picks/today → fastapi service :8000 /picks/today
          - path: /api(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: fastapi
                port:
                  number: 8000
          # React dashboard — everything else
          - path: /()(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: dashboard
                port:
                  number: 80
```

- [ ] **Step 3: Update secret.yaml.example with new key placeholders**

Open `k8s/secret.yaml.example` and add under the existing data section:

```yaml
  REDIS_URL: <base64-encoded: redis://redis:6379/0>
  API_FOOTBALL_KEY: <base64-encoded-key-here>
  OPENWEATHERMAP_KEY: <base64-encoded-key-here>
```

- [ ] **Step 4: Update k8s/configmap.yaml with spread/OU model versions**

Open `k8s/configmap.yaml` and add:

```yaml
  SPREAD_MODEL_VERSION: "1.0"
  OU_MODEL_VERSION: "1.0"
```

- [ ] **Step 5: Commit**

```bash
git add k8s/ingress.yaml k8s/secret.yaml.example k8s/configmap.yaml
git commit -m "feat: activate Ingress routes for api/ and dashboard; add Redis + API key placeholders"
```

---

## Task 7: Update docker-compose for local development

**Files:**
- Modify: `docker-compose.yaml`

- [ ] **Step 1: Replace docker-compose.yaml with all Phase 1 services**

Read the current file first to preserve the postgres + app services, then write:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: soccerbet
      POSTGRES_USER: betuser
      POSTGRES_PASSWORD: betpass
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U betuser -d soccerbet"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data

  app:
    build: .
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    command: ["python", "cli.py", "scheduler"]
    ports:
      - "9090:9090"

  worker:
    build: .
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    command:
      - celery
      - -A
      - app.celery_app
      - worker
      - --loglevel=info
      - --concurrency=2

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8000:8000"

  dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    ports:
      - "8080:80"

volumes:
  postgres-data:
  redis-data:
```

- [ ] **Step 2: Update .env with REDIS_URL**

Add to `.env` (or `.env.example` if that's what's committed):

```
REDIS_URL=redis://redis:6379/0
```

- [ ] **Step 3: Verify all services start**

```bash
docker-compose build
docker-compose up -d postgres redis api dashboard
sleep 5
curl -s http://localhost:8000/health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
docker-compose down
```

Expected:
- `{"status":"ok"}` from API
- `200` from dashboard

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yaml
git commit -m "feat: docker-compose with redis, celery worker, FastAPI, and dashboard services"
```

---

## Task 8: Extend Jenkinsfile with new build stages

**Files:**
- Modify: `Jenkinsfile`

- [ ] **Step 1: Replace Jenkinsfile with extended version**

```groovy
pipeline {
    agent any

    environment {
        ENGINE_IMAGE   = "your-registry/soccer-betting-model"
        API_IMAGE      = "your-registry/soccer-api"
        WORKER_IMAGE   = "your-registry/soccer-betting-model"   // same image as engine, different CMD
        DASHBOARD_IMAGE = "your-registry/soccer-dashboard"
        IMAGE_TAG      = "${env.GIT_COMMIT[0..7]}"
        KUBECONFIG     = credentials('kubeconfig-multiverse')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Test') {
            steps {
                sh '''
                    pip install -r requirements.txt -r requirements.api.txt
                    pytest tests/ -v --tb=short
                '''
            }
        }

        stage('Build Engine') {
            steps {
                sh "docker build -t ${ENGINE_IMAGE}:${IMAGE_TAG} ."
            }
        }

        stage('Build API') {
            steps {
                sh "docker build -f Dockerfile.api -t ${API_IMAGE}:${IMAGE_TAG} ."
            }
        }

        stage('Build Dashboard') {
            steps {
                sh "docker build -f Dockerfile.dashboard -t ${DASHBOARD_IMAGE}:${IMAGE_TAG} ."
            }
        }

        stage('Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry-creds',
                                                  usernameVariable: 'REG_USER',
                                                  passwordVariable: 'REG_PASS')]) {
                    sh '''
                        echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin

                        docker push ${ENGINE_IMAGE}:${IMAGE_TAG}
                        docker tag  ${ENGINE_IMAGE}:${IMAGE_TAG} ${ENGINE_IMAGE}:latest
                        docker push ${ENGINE_IMAGE}:latest

                        docker push ${API_IMAGE}:${IMAGE_TAG}
                        docker tag  ${API_IMAGE}:${IMAGE_TAG} ${API_IMAGE}:latest
                        docker push ${API_IMAGE}:latest

                        docker push ${DASHBOARD_IMAGE}:${IMAGE_TAG}
                        docker tag  ${DASHBOARD_IMAGE}:${IMAGE_TAG} ${DASHBOARD_IMAGE}:latest
                        docker push ${DASHBOARD_IMAGE}:latest
                    '''
                }
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    # Prediction engine
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b set image \
                        deployment/soccer-betting-model \
                        app=${ENGINE_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b rollout status \
                        deployment/soccer-betting-model

                    # Celery worker (same image, different CMD in deployment.yaml)
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b set image \
                        deployment/celery-worker \
                        worker=${ENGINE_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b rollout status \
                        deployment/celery-worker

                    # FastAPI
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b set image \
                        deployment/fastapi \
                        api=${API_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b rollout status \
                        deployment/fastapi

                    # Dashboard
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b set image \
                        deployment/dashboard \
                        dashboard=${DASHBOARD_IMAGE}:${IMAGE_TAG}
                    kubectl --kubeconfig=$KUBECONFIG -n tenant-b rollout status \
                        deployment/dashboard

                    # Apply any new K8s manifests (Redis, Celery, FastAPI, Dashboard)
                    kubectl --kubeconfig=$KUBECONFIG apply -f k8s/ -R
                '''
            }
        }
    }

    post {
        failure {
            echo "Build failed — check test output above."
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add Jenkinsfile
git commit -m "feat: Jenkinsfile — Build API, Build Dashboard, push all images, deploy all services"
```

---

## Task 9: Validate full local stack

This task verifies all Phase 1 services run together locally.

- [ ] **Step 1: Build all images**

```bash
cd /Users/fred/.claude/projects/soccer-betting-model
docker-compose build
```

Expected: 4 images built (app, worker, api, dashboard) with no errors.

- [ ] **Step 2: Start full stack**

```bash
docker-compose up -d
sleep 8
```

- [ ] **Step 3: Run migrations and seed inside app container**

```bash
docker-compose exec app python cli.py migrate
docker-compose exec app python cli.py seed
```

Expected:
- `Database tables created.`
- `Seeded 6 league(s). 0 already existed.`

- [ ] **Step 4: Verify API health**

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/picks/today
```

Expected:
- `{"status":"ok"}`
- `[]` (no picks yet — no data collected)

- [ ] **Step 5: Verify dashboard serves**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
```

Expected: `200`

- [ ] **Step 6: Verify Celery worker connected to Redis**

```bash
docker-compose logs worker | tail -20
```

Expected: Log lines showing `celery@... ready`, `Connected to redis://redis:6379/0`.

- [ ] **Step 7: Shut down**

```bash
docker-compose down
```

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "chore: verified full Phase 1 local stack — all services start cleanly"
```

---

*Phase 1 Infra complete. All three Phase 1 plans are done. The cluster can now be deployed with `kubectl apply -f k8s/ -R` after pushing images.*
