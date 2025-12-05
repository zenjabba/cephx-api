# Ceph Management REST API

A FastAPI-based REST API for managing Ceph CephFS filesystems, CephX authentication, and snapshots.

## Features

- 18 REST endpoints for Ceph management
- CephX authentication management
- CephFS filesystem operations
- Snapshot schedule management
- Cluster monitoring
- API key authentication
- OpenAPI documentation

## Quick Start

```bash
git clone https://github.com/zenjabba/cephx-api.git
cd cephx-api
sudo python3 -m venv /opt/ceph-api/venv
sudo /opt/ceph-api/venv/bin/pip install -r requirements.txt
sudo /opt/ceph-api/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/cluster/status` | Cluster health |
| GET | `/api/v1/cluster/monitors` | Monitor addresses |
| GET | `/api/v1/cluster/df` | Disk usage |
| GET | `/api/v1/fs/fs` | List filesystems |
| POST | `/api/v1/fs/fs` | Create filesystem |
| GET | `/api/v1/fs/fs/{name}` | Filesystem details |
| DELETE | `/api/v1/fs/fs/{name}` | Delete filesystem |
| GET | `/api/v1/fs/fs/{name}/usage` | Filesystem usage |
| GET | `/api/v1/auth/auth` | List CephX clients |
| POST | `/api/v1/auth/auth` | Create CephX client |
| GET | `/api/v1/auth/auth/{name}` | Get client details |
| PUT | `/api/v1/auth/auth/{name}/caps` | Update capabilities |
| DELETE | `/api/v1/auth/auth/{name}` | Delete client |
| GET | `/api/v1/snapshots/fs/{name}/snapshot-schedule` | List schedules |
| POST | `/api/v1/snapshots/fs/{name}/snapshot-schedule` | Add schedule |
| DELETE | `/api/v1/snapshots/fs/{name}/snapshot-schedule` | Remove schedule |

## Authentication

```bash
curl -H "X-API-Key: admin-key" http://localhost:8080/api/v1/cluster/status
```

Default keys: `admin-key` (full access), `readonly-key` (read-only)

## Documentation

- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc

## Requirements

- Python 3.9+
- Ceph cluster with admin access

## License

MIT
