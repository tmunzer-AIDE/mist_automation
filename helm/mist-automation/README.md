# Mist Automation Helm Chart

A Helm chart for deploying Mist Automation Platform application to Kubernetes.

## Prerequisites

- Kubernetes 1.23+
- Helm 3.8+
- PV provisioner support (for persistence)

## Installing the Chart

First, add the required dependency repositories:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm dependency update
```

Install the chart with the release name `mist-automation`:

```bash
helm install mist-automation ./helm/mist-automation \
  --set security.secretKey=$(python -c "import secrets; print(secrets.token_urlsafe(64))") \
  --set mistApi.token=your-mist-api-token \
  --set mistApi.orgId=your-org-id
```

## Uninstalling the Chart

```bash
helm uninstall mist-automation
```

## Configuration

See [values.yaml](values.yaml) for the full list of configurable parameters.

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Docker image repository | `tmunzer/mist-automation` |
| `image.tag` | Docker image tag | `latest` |
| `backend.replicaCount` | Number of backend replicas | `1` |
| `celeryWorker.replicaCount` | Number of Celery worker replicas | `1` |
| `security.secretKey` | JWT secret key (required) | `""` |
| `mistApi.token` | Mist API token | `""` |
| `mistApi.orgId` | Mist Organization ID | `""` |
| `mongodb.enabled` | Use bundled MongoDB | `true` |
| `redis.enabled` | Use bundled Redis | `true` |
| `influxdb.enabled` | Use bundled InfluxDB | `true` |
| `ingress.enabled` | Enable ingress | `false` |

### Using External Databases

To use external MongoDB, Redis, or InfluxDB:

```yaml
mongodb:
  enabled: false
  external:
    url: "mongodb://external-host:27017"

redis:
  enabled: false
  external:
    url: "redis://external-host:6379"

influxdb:
  enabled: false
  external:
    url: "http://external-host:8086"
    token: "your-token"
    org: "your-org"
    bucket: "your-bucket"
```

### Enabling Ingress

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: mist.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: mist-automation-tls
      hosts:
        - mist.example.com
```

### Using Existing Secrets

If you want to manage secrets separately:

```bash
kubectl create secret generic mist-automation-secrets \
  --from-literal=SECRET_KEY=your-secret-key \
  --from-literal=MIST_API_TOKEN=your-token \
  --from-literal=INFLUXDB_TOKEN=your-influxdb-token
```

Then reference it:

```yaml
security:
  existingSecret: mist-automation-secrets
```

## Development

To render templates locally for debugging:

```bash
helm template mist-automation ./helm/mist-automation -f values.yaml --debug
```

To validate the chart:

```bash
helm lint ./helm/mist-automation
```
