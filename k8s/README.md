# Bandhoo Kubernetes Deployment Guide (Minikube)

This directory contains the production-grade Kubernetes manifests for deploying the **Bandhoo** Criminal Law Decision Support & Complaint Structuring Backend to a local **Minikube** cluster on macOS (Apple Silicon / ARM64 or Intel).

---

## 1. Architecture Overview

```
                      +------------------------------------------+
                      |         Developer Workstation (macOS)     |
                      |   Browser / curl (http://localhost:8001) |
                      +--------------------+---------------------+
                                           |
                    (Port-Forward or Minikube Service URL)
                                           |
                                           v
+-------------------------------------------------------------------------------+
| Minikube Cluster (Single-Node Kubernetes)                                     |
|                                                                               |
|   +-----------------------------------------------------------------------+   |
|   | Service: bandhoo-backend-service (NodePort: 30081, TargetPort: 8001)   |   |
|   +-----------------------------------+-----------------------------------+   |
|                                       |                                       |
|                                       v                                       |
|   +-----------------------------------------------------------------------+   |
|   | Deployment: bandhoo-backend (Replicas: 1)                             |   |
|   |                                                                       |   |
|   |   Pod: bandhoo-backend-xxxxxxxxx-xxxxx                                |   |
|   |   +---------------------------------------------------------------+   |   |
|   |   | Container: bandhoo-backend (image: bandhoo-backend:1.0.0)      |   |   |
|   |   | User: appuser (UID: 10001, non-root)                          |   |   |
|   |   | Probes:                                                       |   |   |
|   |   |   - startupProbe:   HTTP GET /health (FastAPI + DB lifespan)  |   |   |
|   |   |   - livenessProbe:  HTTP GET /health                          |   |   |
|   |   |   - readinessProbe: HTTP GET /health                          |   |   |
|   |   | Resources:                                                    |   |   |
|   |   |   - Requests: 100m CPU, 256Mi RAM                             |   |   |
|   |   |   - Limits:   500m CPU, 512Mi RAM                             |   |   |
|   |   | Endpoints:                                                    |   |   |
|   |   |   - /health (Liveness/Readiness probe)                        |   |   |
|   |   |   - /metrics (Prometheus scrape endpoint)                     |   |   |
|   |   |   - /api/classify-offence (BM25 Legal Engine)                 |   |   |
|   |   +---------------------------------------------------------------+   |   |
|   +-----------------------------------------------------------------------+   |
|                                                                               |
|   ConfigMap: bandhoo-config (PORT, HOST, STORAGE_DIR, CORS, DB URL)           |
|   Secret:    bandhoo-secrets (Optional GEMINI_API_KEY)                        |
+-------------------------------------------------------------------------------+
```

---

## 2. Manifest Inventory

| Manifest | Kind | Purpose |
| :--- | :--- | :--- |
| [`configmap.yaml`](file:///Users/tanaya/Desktop/Bandhoo-1/k8s/configmap.yaml) | `ConfigMap` | Non-sensitive runtime variables (`BANDHOO_PORT`, `BANDHOO_HOST`, `ENABLE_METRICS`, `DATABASE_URL`, etc.). |
| [`secret.example.yaml`](file:///Users/tanaya/Desktop/Bandhoo-1/k8s/secret.example.yaml) | `Secret` | Template for confidential credentials (`GEMINI_API_KEY`). |
| [`deployment.yaml`](file:///Users/tanaya/Desktop/Bandhoo-1/k8s/deployment.yaml) | `Deployment` | Manages the Bandhoo backend Pods, health probes, resource quotas, and unprivileged security contexts. |
| [`service.yaml`](file:///Users/tanaya/Desktop/Bandhoo-1/k8s/service.yaml) | `Service` | Exposes the Pods via a `NodePort` (`30081`) for access outside the cluster. |

---

## 3. Prerequisites

1. **Docker Desktop**: Running on macOS.
2. **Minikube**: Installed (`minikube version`).
3. **kubectl**: Installed (`kubectl version --client`).
4. **Local Image Built**: `bandhoo-backend:1.0.0` built via Docker in Phase 2.

---

## 4. Step-by-Step Deployment Guide

### Step 1: Start Minikube
Start the Minikube cluster using the Docker driver (optimized for Apple Silicon / ARM64):

```bash
minikube start --driver=docker
```

### Step 2: Load the Local Docker Image into Minikube
Because Minikube operates in its own container/VM environment, it cannot automatically read Docker Desktop's host image cache. Transfer the image directly into Minikube's runtime:

```bash
minikube image load bandhoo-backend:1.0.0
```

Verify that the image is available in Minikube:
```bash
minikube image ls | grep bandhoo-backend
```

### Step 3: Apply Kubernetes Manifests

Apply the ConfigMap first:
```bash
kubectl apply -f k8s/configmap.yaml
```

*(Optional)* Create the Secret if you wish to test with Google Gemini LLM reasoning:
```bash
kubectl create secret generic bandhoo-secrets \
  --from-literal=GEMINI_API_KEY="your_api_key_here" \
  --dry-run=client -o yaml | kubectl apply -f -
```
*(Note: If omitted, the deployment will still start cleanly because `GEMINI_API_KEY` is configured with `optional: true` in `deployment.yaml`.)*

Apply the Deployment and Service:
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

---

## 5. Verification Commands

### Check Pod Status
```bash
kubectl get pods -l app=bandhoo-backend -w
```
Wait until the Pod status transitions to `Running` and readiness shows `1/1`:
```
NAME                               READY   STATUS    RESTARTS   AGE
bandhoo-backend-xxxxxxxxxx-xxxxx   1/1     Running   0          30s
```

### Check Deployment & Service
```bash
kubectl get deployments -l app=bandhoo-backend
kubectl get services -l app=bandhoo-backend
```

### Inspect Pod Startup Logs
Check that database tables auto-initialized and Prometheus metrics were registered:
```bash
kubectl logs -l app=bandhoo-backend --tail=50
```
Expected log entries:
```
[Startup] Database tables initialized and verified successfully.
[Metrics] Prometheus metrics instrumentation actively exposed at /metrics.
Uvicorn running on http://0.0.0.0:8001
```

---

## 6. Accessing the Application

There are two reliable methods to access Bandhoo from your Mac:

### Method A: Port-Forwarding (Recommended for quick testing)
Forward local port `8001` directly to the Kubernetes service:

```bash
kubectl port-forward svc/bandhoo-backend-service 8001:8001
```

In a separate terminal, test the endpoints:
```bash
# 1. Health Probe
curl -i http://localhost:8001/health

# 2. Prometheus Metrics
curl -i http://localhost:8001/metrics | head -n 25

# 3. Offence Classification (Legal Engine)
curl -X POST http://localhost:8001/api/classify-offence \
  -H "Content-Type: application/json" \
  -d '{"narrative": "Two men cornered me near Dadar station and snatched my bag containing Rs 10000 cash."}'
```

### Method B: Minikube Service URL (Direct NodePort)
Ask Minikube to open a tunnel and print the public NodePort endpoint:

```bash
minikube service bandhoo-backend-service --url
```
Use the printed URL (e.g., `http://127.0.0.1:xxxxx`) to query `/health` and `/metrics`.

---

## 7. Operational Demonstrations

### A. Pod Self-Healing Demonstration
Demonstrate Kubernetes resilience by deliberately terminating a running pod:

```bash
# 1. Note the current pod name
POD_NAME=$(kubectl get pods -l app=bandhoo-backend -o jsonpath="{.items[0].metadata.name}")
echo "Current pod: $POD_NAME"

# 2. Delete the pod
kubectl delete pod "$POD_NAME"

# 3. Observe the Deployment automatically launching a replacement pod
kubectl get pods -l app=bandhoo-backend -w
```
The Deployment controller detects that the replica count dropped from 1 to 0 and immediately schedules a new pod to restore the desired state.

### B. Horizontal Scaling Demonstration
Scale the backend to 3 replicas:

```bash
kubectl scale deployment bandhoo-backend --replicas=3
kubectl get pods -l app=bandhoo-backend -w
```

Scale back down to 1 replica:
```bash
kubectl scale deployment bandhoo-backend --replicas=1
```

---

## 8. Database Persistence Architecture Note

- In this Phase 5A configuration, Bandhoo runs with **SQLite** (`DATABASE_URL=sqlite:///bandhoo_persistence.db`) inside the single Pod (`replicas: 1`).
- The persistent SQLite file is stored at `/app/bandhoo_persistence.db` within the container's writable layer.
- **Why a PersistentVolumeClaim (PVC) is not introduced in Phase 5A**:
  1. SQLite relies on POSIX file locks. Attaching a shared PVC across scaled replicas (`replicas > 1`) causes `database is locked` concurrency errors.
  2. For local Minikube and stateless container testing, in-memory/ephemeral SQLite auto-initialization via FastAPI's `lifespan` hook satisfies all evaluation criteria without complex local hostPath storage bindings.
  3. In cloud production (Azure Container Apps / Phase 7), relational persistence transitions to a managed **PostgreSQL** instance configured via `DATABASE_URL=postgresql://...`.

---

## 9. Teardown & Cleanup

To remove all Bandhoo Kubernetes resources from Minikube:

```bash
# 1. Delete Kubernetes resources
kubectl delete -f k8s/service.yaml
kubectl delete -f k8s/deployment.yaml
kubectl delete -f k8s/configmap.yaml
kubectl delete secret bandhoo-secrets --ignore-not-found

# 2. (Optional) Stop Minikube
minikube stop
```

