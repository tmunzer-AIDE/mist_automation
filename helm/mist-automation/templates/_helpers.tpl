{{/*
Expand the name of the chart.
*/}}
{{- define "mist-automation.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mist-automation.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "mist-automation.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mist-automation.labels" -}}
helm.sh/chart: {{ include "mist-automation.chart" . }}
{{ include "mist-automation.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mist-automation.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mist-automation.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "mist-automation.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mist-automation.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Backend specific labels
*/}}
{{- define "mist-automation.backend.labels" -}}
{{ include "mist-automation.labels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{- define "mist-automation.backend.selectorLabels" -}}
{{ include "mist-automation.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Celery worker specific labels
*/}}
{{- define "mist-automation.celery-worker.labels" -}}
{{ include "mist-automation.labels" . }}
app.kubernetes.io/component: celery-worker
{{- end }}

{{- define "mist-automation.celery-worker.selectorLabels" -}}
{{ include "mist-automation.selectorLabels" . }}
app.kubernetes.io/component: celery-worker
{{- end }}

{{/*
Celery beat specific labels
*/}}
{{- define "mist-automation.celery-beat.labels" -}}
{{ include "mist-automation.labels" . }}
app.kubernetes.io/component: celery-beat
{{- end }}

{{- define "mist-automation.celery-beat.selectorLabels" -}}
{{ include "mist-automation.selectorLabels" . }}
app.kubernetes.io/component: celery-beat
{{- end }}

{{/*
MongoDB connection URL
*/}}
{{- define "mist-automation.mongodbUrl" -}}
{{- if .Values.mongodb.enabled }}
{{- printf "mongodb://%s-mongodb:27017" .Release.Name }}
{{- else }}
{{- .Values.mongodb.external.url }}
{{- end }}
{{- end }}

{{/*
Redis connection URL
*/}}
{{- define "mist-automation.redisUrl" -}}
{{- if .Values.redis.enabled }}
{{- printf "redis://%s-redis-master:6379" .Release.Name }}
{{- else }}
{{- .Values.redis.external.url }}
{{- end }}
{{- end }}

{{/*
InfluxDB URL
*/}}
{{- define "mist-automation.influxdbUrl" -}}
{{- if .Values.influxdb.enabled }}
{{- printf "http://%s-influxdb:8086" .Release.Name }}
{{- else }}
{{- .Values.influxdb.external.url }}
{{- end }}
{{- end }}

{{/*
InfluxDB Token
*/}}
{{- define "mist-automation.influxdbToken" -}}
{{- if .Values.influxdb.enabled }}
{{- .Values.influxdb.auth.admin.token }}
{{- else }}
{{- .Values.influxdb.external.token }}
{{- end }}
{{- end }}

{{/*
InfluxDB Organization
*/}}
{{- define "mist-automation.influxdbOrg" -}}
{{- if .Values.influxdb.enabled }}
{{- .Values.influxdb.auth.admin.org }}
{{- else }}
{{- .Values.influxdb.external.org }}
{{- end }}
{{- end }}

{{/*
InfluxDB Bucket
*/}}
{{- define "mist-automation.influxdbBucket" -}}
{{- if .Values.influxdb.enabled }}
{{- .Values.influxdb.auth.admin.bucket }}
{{- else }}
{{- .Values.influxdb.external.bucket }}
{{- end }}
{{- end }}

{{/*
Secret name for sensitive data
*/}}
{{- define "mist-automation.secretName" -}}
{{- if .Values.security.existingSecret }}
{{- .Values.security.existingSecret }}
{{- else }}
{{- include "mist-automation.fullname" . }}
{{- end }}
{{- end }}

{{/*
Image pull secrets
*/}}
{{- define "mist-automation.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
