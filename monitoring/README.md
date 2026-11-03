# Bandhoo Local Prometheus + Grafana Monitoring Stack

This directory contains the production-grade local monitoring stack for the **Bandhoo** Decision-Support Backend deployed on **AWS ECS Fargate** in the `ap-south-1` (Mumbai) region.

---

## 1. Architecture Overview

```
       +-------------------------------------------------------------+
       | AWS ECS Fargate Backend                                     |
       | Host: 13.232.16.110:8001                                    |
       | Endpoints:                                                  |
       |   - /health  (System status & probes)                       |
       |   - /metrics (Prometheus-FastAPI-Instrumentator telemetry)   |
       +-------------------------------------------------------------+
                                      ^
                                      | HTTP Scrape (Every 15s)
                                      |
+-------------------------------------|-------------------------------+
| Local Docker Monitoring Stack       |                               |
|                                     |                               |
|   +----------------------------+    |                               |
|   | Prometheus (v2.51.0)       |----+                               |
|   |   - Scrape Target: :8001   |                                    |
|   |   - Web UI: localhost:9090 |                                    |
|   |   - Volume: prometheus_data|                                    |
|   |   - Lifecycle API: Enabled |                                    |
|   +----------------------------+                                    |
|                 ^                                                   |
|                 | PromQL Proxy Queries                              |
|                 v                                                   |
|   +----------------------------+                                    |
|   | Grafana (v10.4.1)          |                                    |
|   |   - Auto-provisioned DS    |                                    |
|   |   - Pre-built Dashboard    |                                    |
|   |   - Web UI: localhost:3000 |                                    |
|   |   - Volume: grafana_data   |                                    |
|   +----------------------------+                                    |
+---------------------------------------------------------------------+
```

---

## 2. Directory Structure

```
monitoring/
├── docker-compose.yml                          # Multi-container stack definition
├── .env.example                                # Environment credentials template
├── README.md                                   # Operational and troubleshooting guide
├── prometheus/
│   └── prometheus.yml                          # Scrape target & interval configuration
└── grafana/
    ├── dashboards/
    │   └── bandhoo-overview.json               # Comprehensive pre-configured dashboard
    └── provisioning/
        ├── dashboards/
        │   └── dashboards.yml                  # Auto-loads dashboards from file
        └── datasources/
            └── datasources.yml                 # Auto-provisions Prometheus default source
```

---

## 3. Metric Inventory & Dashboard Panels

The dashboard uses the exact metric names and labels emitted by `prometheus-fastapi-instrumentator` and the Python runtime in `main.py`:

| Panel Title | Metric Type | Exact PromQL Expression | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend Target Health** | Instant Stat | `up{job="bandhoo-backend"}` | Displays green `UP` (1) or red `DOWN` (0). |
| **Requests In Progress** | Gauge Stat | `sum(bandhoo_requests_in_progress{job="bandhoo-backend"})` | Active concurrent requests being processed. |
| **Total Throughput** | Timeseries | `sum(rate(http_requests_total{job="bandhoo-backend"}[1m]))` | Overall traffic in requests per second. |
| **Request Rate by Handler** | Timeseries | `sum by (handler) (rate(http_requests_total{job="bandhoo-backend"}[1m]))` | API throughput broken down by route endpoint. |
| **Requests by Status Code** | Stacked Bars | `sum by (status) (rate(http_requests_total{job="bandhoo-backend"}[1m]))` | Distribution of 2xx, 3xx, 4xx, and 5xx responses. |
| **Request Duration / Latency** | Timeseries | <ul><li>p95: `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="bandhoo-backend"}[1m])))`</li><li>p50: `histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{job="bandhoo-backend"}[1m])))`</li><li>Avg: `sum(rate(http_request_duration_seconds_sum{job="bandhoo-backend"}[1m])) / sum(rate(http_request_duration_seconds_count{job="bandhoo-backend"}[1m]))`</li></ul> | Tracks p95, median (p50), and mean latency in seconds. |
| **Process Memory (RSS/VSZ)** | Timeseries | <ul><li>RSS: `process_resident_memory_bytes{job="bandhoo-backend"}`</li><li>VSZ: `process_virtual_memory_bytes{job="bandhoo-backend"}`</li></ul> | Resident Set Size vs. Virtual Memory footprint. |
| **Process CPU Usage** | Timeseries | `rate(process_cpu_seconds_total{job="bandhoo-backend"}[1m]) * 100` | Percentage of CPU core utilized by the backend. |
| **Python GC Activity** | Timeseries | `sum by (generation) (rate(python_gc_collections_total{job="bandhoo-backend"}[1m]))` | Garbage collection frequency per generation (0, 1, 2). |

---

## 4. Prerequisites

1. **Docker Desktop**: Running locally with Compose V2 support (`docker compose version`).
2. **AWS Inbound Access**: Ensure your public IP address is permitted in the AWS Security Group for port `8001`.
   ```bash
   # Verify connectivity to the ECS Fargate metrics endpoint:
   curl -I http://13.232.16.110:8001/metrics
   ```

---

## 5. Startup & Operational Instructions

### Step 5.1: Configure Environment Variables

```bash
cd monitoring
cp .env.example .env
# Edit .env if you wish to change GRAFANA_ADMIN_USER or GRAFANA_ADMIN_PASSWORD
```

### Step 5.2: Launch the Monitoring Stack

```bash
docker compose up -d
```

### Step 5.3: Verify Running Containers

```bash
docker compose ps
```

Expected output:
```
NAME                 IMAGE                     COMMAND                  SERVICE      STATUS      PORTS
bandhoo-grafana      grafana/grafana:10.4.1    "/run.sh"                grafana      running     127.0.0.1:3000->3000/tcp
bandhoo-prometheus   prom/prometheus:v2.51.0   "/bin/prometheus --c…"   prometheus   running     127.0.0.1:9090->9090/tcp
```

---

## 6. Accessing the User Interfaces

### Prometheus Web UI
* **URL**: `http://127.0.0.1:9090` (or `http://localhost:9090`)
* **Target Health**: Navigate to **Status -> Targets**. The `bandhoo-backend` endpoint (`http://13.232.16.110:8001/metrics`) should display state **UP**.

### Grafana Web UI
* **URL**: `http://127.0.0.1:3000` (or `http://localhost:3000`)
* **Username**: Value of `GRAFANA_ADMIN_USER` configured in your `monitoring/.env` (default: `admin`)
* **Password**: Value of `GRAFANA_ADMIN_PASSWORD` configured in your `monitoring/.env`
* **Dashboard Location**: Navigate to **Dashboards -> Bandhoo -> Bandhoo Legal Decision-Support - Backend Telemetry**.

---

## 7. Dynamic Fargate Task IP Updates (Zero-Downtime Reload)

AWS Fargate tasks assign dynamic public IPs upon startup. When the backend task is restarted or redeployed, the public IP may change.

### Option A: Hot-Reload Prometheus Target Without Restarting (Recommended)

1. **Discover the new Fargate public IP**:
   ```bash
   TASK_ARN=$(aws ecs list-tasks --cluster bandhoo-cluster --service-name bandhoo-backend-service --query 'taskArns[0]' --output text --region ap-south-1)
   ENI_ID=$(aws ecs describe-tasks --cluster bandhoo-cluster --tasks $TASK_ARN --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text --region ap-south-1)
   NEW_IP=$(aws ec2 describe-network-interfaces --network-interface-ids $ENI_ID --query 'NetworkInterfaces[0].Association.PublicIp' --output text --region ap-south-1)
   echo "New Public IP: $NEW_IP"
   ```

2. **Update the target in `monitoring/prometheus/prometheus.yml`**:
   Replace `13.232.16.110:8001` with `<NEW_IP>:8001`.

3. **Trigger Prometheus Hot-Reload**:
   Because Prometheus is launched with `--web.enable-lifecycle`, invoke the reload API:
   ```bash
   curl -X POST http://127.0.0.1:9090/-/reload
   ```
   *Prometheus will immediately start scraping the new IP without dropping container history or restarting.*

### Option B: Restart Prometheus Container

```bash
docker compose restart prometheus
```

---

## 8. Shutdown & Data Management

### Normal Shutdown (Preserves Metrics History)
```bash
docker compose down
```

### Complete Teardown (Purges Docker Volumes)
```bash
docker compose down -v
```

---

## 9. Common Troubleshooting

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **Prometheus Target state `DOWN` (`context deadline exceeded`)** | AWS Security Group blocks inbound traffic from your local IP. | Run `curl -I http://13.232.16.110:8001/metrics`. If it hangs, update `inbound_cidr_blocks = ["<YOUR_PUBLIC_IP>/32"]` in `terraform/terraform.tfvars` and apply. |
| **Prometheus Target state `DOWN` (`connection refused`)** | ECS task restarted with a new dynamic public IP. | Query the new public IP using AWS CLI (Section 7), update `prometheus/prometheus.yml`, and execute `curl -X POST http://127.0.0.1:9090/-/reload`. |
| **Grafana Container fails on startup (`GRAFANA_ADMIN_PASSWORD must be configured`)** | Missing `monitoring/.env` file. | Copy `.env.example` to `.env` (`cp .env.example .env`) and set `GRAFANA_ADMIN_PASSWORD`. |
| **Port Conflict on 3000 or 9090** | Another local process or service is using the port. | Identify the conflicting process (`lsof -i :3000` or `lsof -i :9090`) or adjust the host port mapping in `docker-compose.yml` (e.g. `127.0.0.1:3001:3000`). |


