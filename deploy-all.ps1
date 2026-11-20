# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# =============================================================================
# Registry Center - One-Click GCP Deployment
# =============================================================================
# This script handles EVERYTHING:
#   1. Checks prerequisites (gcloud installed, logged in)
#   2. Creates GCP resources (Cloud SQL, Artifact Registry, etc.) if needed
#   3. Builds and deploys to Cloud Run
#
# USAGE:  Just run this script in PowerShell:
#   .\deploy-all.ps1 -DevelopmentOnly
#
# You will be prompted for your GCP Project ID and a database password.
# =============================================================================
#
# Configuration surface (all optional; the environment variable of the same
# name is used when set, otherwise the value is prompted for or defaulted):
#   -ServiceName <name>      Cloud Run service and Cloud SQL instance prefix.
#                            Default registry-center; must match
#                            ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$.
#   -GCPProjectID <id>       GCP project; falls back to GCP_PROJECT_ID, then a
#                            prompt. Required - the script exits 1 without it.
#   -DevelopmentOnly         Mandatory: without it the script refuses to run at
#                            all, because Cloud Run provides no verified owner
#                            identity.
#   GCP_REGION               Default asia-east1.
#   DB_PASSWORD              PostgreSQL password for the generated user. Read
#                            from Secret Manager <service>-db-password-<project>
#                            when available, otherwise prompted for and
#                            auto-generated (16 chars) when left empty. It is
#                            never passed as a literal --set-env-vars value: it
#                            is stored in Secret Manager and injected with
#                            --set-secrets.
#
# Derived values (not operator-settable): Artifact Registry repository
# "openan-repo", Cloud SQL instance <service>-db (POSTGRES_15, db-f1-micro,
# 10 GB SSD), database <service with '-' replaced by '_'>, user = the first
# '-'-separated segment of the service name, service account <service>-sa with
# roles/cloudsql.client and secretmanager.secretAccessor.
#
# Environment variables that must NOT be exported by the caller: the script
# deletes the residual ones below on every run so a previous deployment in the
# same PowerShell session cannot leak into this one.
# =============================================================================

param(
    [string]$ServiceName = "",
    [string]$GCPProjectID = "",
    [switch]$DevelopmentOnly
)

# This source deployment has no verified per-agent identity gateway. Cloud Run
# TLS termination/IAM alone does not supply an AgentCard owner certificate CN.
# Refuse BEFORE creating cloud resources instead of deploying a healthy-looking
# service whose ownership writes all return 401.
if (-not $DevelopmentOnly) {
    Write-Error "This Cloud Run script is development-only: it cannot provide verified owner identities. Use an mTLS deployment or a separately configured trusted identity gateway for production. Pass -DevelopmentOnly only for an IAM-protected demo without owner isolation/signing."
    exit 1
}

$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false

# ── Clear residual env vars from previous runs ──────────────────────────────
# Prevents cross-contamination when deploying multiple services in the same
# PowerShell session.
# REGISTRY_FORWARDED_ALLOW_IPS is cleared even though it is also an image
# default: this script sets it to "*" (see the Cloud Run env block below).
$cleanupVars = @('GCP_PROJECT_ID', 'GCP_REGION', 'DB_PASSWORD', 'PERSISTENCE_MODE', 'DB_HOST', 'DB_PORT',
                 'DB_NAME', 'DB_USERNAME', 'DB_POOL_MIN', 'DB_POOL_MAX',
                 'REGISTRY_ENABLE_HTTPS', 'REGISTRY_FORWARDED_ALLOW_IPS',
                 'REGISTRY_OWNER_VALIDATION_MODE')
foreach ($v in $cleanupVars) {
    Remove-Item "env:$v" -ErrorAction SilentlyContinue
}

# Use param value if provided, otherwise keep current env value for Read-Host fallback
if ($GCPProjectID) { $env:GCP_PROJECT_ID = $GCPProjectID }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host ""
Write-Host "===================================================================="
Write-Host "  Registry Center - GCP Cloud Run Deployment (All-in-One)"
Write-Host "===================================================================="
Write-Host ""

# ── Step 1: Check gcloud ────────────────────────────────────────────────────
Write-Host "[1/5] Checking gcloud CLI..."
$gcloudPath = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloudPath) {
    Write-Host ""
    Write-Host "ERROR: gcloud CLI is not installed."
    Write-Host ""
    Write-Host "Install it now (run in PowerShell as Administrator):"
    Write-Host "  (New-Object Net.WebClient).DownloadFile('https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe', `"`$env:TEMP\gcloud-installer.exe`"); Start-Process `"`$env:TEMP\gcloud-installer.exe`" -Wait"
    Write-Host ""
    Write-Host "After installation, CLOSE this PowerShell, open a NEW one, and run this script again."
    exit 1
}
Write-Host "  OK: gcloud found"

# ── Step 2: Check login ─────────────────────────────────────────────────────
Write-Host "[2/5] Checking GCP login status..."
$account = gcloud auth list --format="value(account)" 2>$null
if (-not $account) {
    Write-Host ""
    Write-Host "You need to log in to your Google Cloud account."
    Write-Host "A browser window will open..."
    gcloud auth login
    Write-Host ""
    Write-Host "After login, run this script again."
    exit 0
}
Write-Host "  Logged in as: ${account}"

# ── Step 3: Collect configuration ───────────────────────────────────────────
Write-Host "[3/5] Collecting deployment configuration..."
Write-Host ""

if (-not $env:GCP_PROJECT_ID) {
    $env:GCP_PROJECT_ID = Read-Host "Enter your GCP Project ID"
}
if (-not $env:GCP_PROJECT_ID) {
    Write-Host "ERROR: GCP Project ID is required."
    exit 1
}

# Resolve and validate service name
if (-not $ServiceName) { $ServiceName = "registry-center" }
if ($ServiceName -notmatch '^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$') {
    Write-Host "ERROR: ServiceName '$ServiceName' is invalid. Use lowercase letters, digits, and hyphens only."
    exit 1
}

if (-not $env:GCP_REGION) { $env:GCP_REGION = "asia-east1" }
if (-not $env:DB_PASSWORD) {
    # Try to retrieve existing password from Secret Manager
    # Use project-specific secret name to isolate passwords across GCP projects
    $sanitizeProj = $env:GCP_PROJECT_ID -replace '[^a-zA-Z0-9]', '-'
    $lookupSecretID = "${ServiceName}-db-password-${sanitizeProj}"
    $secretTmpRead = Join-Path $env:TEMP "${ServiceName}-secret-read.tmp"
    $readOk = $false
    try {
        gcloud secrets versions access latest --secret="$lookupSecretID" --project="$env:GCP_PROJECT_ID" --out-file="$secretTmpRead" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $rawBytes = [System.IO.File]::ReadAllBytes($secretTmpRead)
            if ($rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF) {
                $rawBytes = $rawBytes[3..($rawBytes.Length - 1)]
            }
            $existingPassword = [System.Text.Encoding]::UTF8.GetString($rawBytes).TrimEnd("`r", "`n")
            if ($existingPassword -and $existingPassword -notmatch '^\d+(\s+\d+)+$') {
                $env:DB_PASSWORD = $existingPassword
                $readOk = $true
                Write-Host "  Using existing password from Secret Manager ($lookupSecretID)"
            } else {
                Write-Host "  WARNING: Stored password appears corrupted (ASCII byte values), will regenerate."
            }
        }
    } catch { }
    if (Test-Path $secretTmpRead) { Remove-Item $secretTmpRead -Force }

    if (-not $readOk) {
        $env:DB_PASSWORD = Read-Host "Set a password for the PostgreSQL database (or press Enter to auto-generate)"
        if (-not $env:DB_PASSWORD) {
            $env:DB_PASSWORD = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object {[char]$_})
            Write-Host '  Auto-generated password (stored in Secret Manager; not printed).'
        }
    }
}

Write-Host ""
Write-Host "  Configuration:"
Write-Host "    Service    : ${ServiceName}"
Write-Host "    Project ID : $env:GCP_PROJECT_ID"
Write-Host "    Region     : $env:GCP_REGION"
Write-Host ""

# ── Step 4: Setup GCP resources (idempotent - safe to re-run) ───────────────
Write-Host "[4/5] Setting up GCP resources (this may take 5-10 minutes)..."
Write-Host ""

$SERVICE_NAME    = $ServiceName
$ARTIFACT_REPO   = "openan-repo"
$CLOUDSQL_INST   = "${SERVICE_NAME}-db"
$DB_NAME         = ($SERVICE_NAME -replace '-', '_')
$DB_USER         = ($SERVICE_NAME -split '-')[0]
$SA_NAME         = "${SERVICE_NAME}-sa"
$SA_EMAIL        = "${SA_NAME}@$env:GCP_PROJECT_ID.iam.gserviceaccount.com"
$secretProjectID = ($env:GCP_PROJECT_ID -replace '[^a-zA-Z0-9]', '-')
$SECRET_ID       = "${SERVICE_NAME}-db-password-${secretProjectID}"
$DB_TIER         = "db-f1-micro"
$CLOUDSQL_CONN   = $env:GCP_PROJECT_ID + ":" + $env:GCP_REGION + ":" + $CLOUDSQL_INST

# Enable APIs
Write-Host "  Enabling GCP APIs..."
gcloud services enable artifactregistry.googleapis.com sqladmin.googleapis.com run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null

# Artifact Registry
Write-Host "  Setting up Artifact Registry..."
$repoExists = gcloud artifacts repositories describe "${ARTIFACT_REPO}" --location="$env:GCP_REGION" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null; $repoExists = ($LASTEXITCODE -eq 0)
if (-not $repoExists) {
    gcloud artifacts repositories create "${ARTIFACT_REPO}" --repository-format=docker --location="$env:GCP_REGION" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    Write-Host "    Already exists, skipping."
}

# Cloud SQL
Write-Host "  Setting up Cloud SQL PostgreSQL..."
$sqlExists = gcloud sql instances describe "${CLOUDSQL_INST}" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null; $sqlExists = ($LASTEXITCODE -eq 0)
if (-not $sqlExists) {
    gcloud sql instances create "${CLOUDSQL_INST}" --database-version=POSTGRES_15 --tier="${DB_TIER}" --region="$env:GCP_REGION" --storage-size=10 --storage-type=SSD --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    Write-Host "    Already exists, skipping."
}

# Database
$dbExists = gcloud sql databases describe "${DB_NAME}" --instance="${CLOUDSQL_INST}" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null; $dbExists = ($LASTEXITCODE -eq 0)
if (-not $dbExists) {
    gcloud sql databases create "${DB_NAME}" --instance="${CLOUDSQL_INST}" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    Write-Host "    Database already exists, skipping."
}

# DB User
$userExists = gcloud sql users list --instance="${CLOUDSQL_INST}" --project="$env:GCP_PROJECT_ID" --format="value(name)" 2>&1 | Out-Null; $userExists = ($LASTEXITCODE -eq 0) -and ((gcloud sql users list --instance="${CLOUDSQL_INST}" --project="$env:GCP_PROJECT_ID" --format="value(name)" 2>&1) -match "^${DB_USER}$")
if (-not $userExists) {
    gcloud sql users create "${DB_USER}" --instance="${CLOUDSQL_INST}" --password="$env:DB_PASSWORD" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    Write-Host "    DB user already exists, updating password..."
    gcloud sql users set-password "${DB_USER}" --instance="${CLOUDSQL_INST}" --password="$env:DB_PASSWORD" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
}

# Secret Manager
Write-Host "  Storing DB password in Secret Manager (${'$'}SECRET_ID = ${SECRET_ID})..."
$secretExists = gcloud secrets describe "${SECRET_ID}" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null; $secretExists = ($LASTEXITCODE -eq 0)
$secretTmpFile = Join-Path $env:TEMP "${SERVICE_NAME}-secret.tmp"
[System.IO.File]::WriteAllText($secretTmpFile, $env:DB_PASSWORD, (New-Object System.Text.UTF8Encoding $false))
if (-not $secretExists) {
    gcloud secrets create "${SECRET_ID}" --data-file="$secretTmpFile" --replication-policy="automatic" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    gcloud secrets versions add "${SECRET_ID}" --data-file="$secretTmpFile" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
    Write-Host "    Secret already exists, updated with new value."
}
Remove-Item $secretTmpFile -Force

# Service Account
Write-Host "  Setting up service account..."
$saExists = gcloud iam service-accounts describe "${SA_EMAIL}" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null; $saExists = ($LASTEXITCODE -eq 0)
if (-not $saExists) {
    gcloud iam service-accounts create "${SA_NAME}" --display-name="Registry Center Service Account" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    Write-Host "    Service account already exists, skipping."
}

# IAM bindings (idempotent, gcloud handles duplicates silently)
gcloud projects add-iam-policy-binding "$env:GCP_PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/cloudsql.client" --condition=None 2>&1 | Out-Null
gcloud secrets add-iam-policy-binding "${SECRET_ID}" --member="serviceAccount:${SA_EMAIL}" --role="roles/secretmanager.secretAccessor" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null

Write-Host "  Setup done!"
Write-Host ""

# ── Step 5: Deploy to Cloud Run ─────────────────────────────────────────────
Write-Host "[5/5] Deploying to Cloud Run (building & deploying, ~5 minutes)..."
Write-Host ""

# Build the env vars string separately to ensure correct expansion
# Runtime configuration of the deployed revision. These reach the container as
# environment variables, where bin/entrypoint.sh rewrites them into
# etc/conf/server.conf and etc/conf/persistence.conf and
# common/util/app_config.py applies the REGISTRY_* ones directly.
#   PERSISTENCE_MODE=postgresql      use the Cloud SQL instance below
#   DB_HOST=/cloudsql/<connection>   Unix socket path, not a TCP host
#   DB_PORT, DB_NAME, DB_USERNAME    generated above
#   DB_POOL_MIN=2, DB_POOL_MAX=10    conservative pool for the db-f1-micro tier
#   REGISTRY_ENABLE_HTTPS=false      Cloud Run terminates TLS in front of the container
#   REGISTRY_FORWARDED_ALLOW_IPS=*   trust the platform front end (its address is not
#                                    stable). Never use "*" for owner.trusted.proxy.ips
#   REGISTRY_OWNER_VALIDATION_MODE=relaxed
#   REGISTRY_OWNER_ISOLATION_ENABLED=false   no verified owner identity; this is what
#   REGISTRY_VERIFY_CLIENT=false             makes the script development-only
#   REGISTRY_SIGNATURE_VALIDATION_ENABLED=false
#   REGISTRY_REGISTRY_SIGN_ENABLED=false
# DB_PASSWORD is deliberately not listed here: it is injected from Secret Manager
# by --set-secrets below so it never appears in the revision's plain env vars.
$envVars = "PERSISTENCE_MODE=postgresql"
$envVars += ",DB_HOST=/cloudsql/$CLOUDSQL_CONN"
$envVars += ",DB_PORT=5432"
$envVars += ",DB_NAME=$DB_NAME"
$envVars += ",DB_USERNAME=$DB_USER"
$envVars += ",DB_POOL_MIN=2"
$envVars += ",DB_POOL_MAX=10"
$envVars += ",REGISTRY_ENABLE_HTTPS=false"
# Cloud Run terminates TLS and rewrites X-Forwarded-* itself, and the proxy address
# is not stable, so the platform front end is trusted here. Never use "*" for
# owner.trusted.proxy.ips (ownership authentication stays on the verified identity).
$envVars += ",REGISTRY_FORWARDED_ALLOW_IPS=*"
$envVars += ",REGISTRY_OWNER_VALIDATION_MODE=relaxed"
$envVars += ",REGISTRY_OWNER_ISOLATION_ENABLED=false"
$envVars += ",REGISTRY_VERIFY_CLIENT=false"
$envVars += ",REGISTRY_SIGNATURE_VALIDATION_ENABLED=false"
$envVars += ",REGISTRY_REGISTRY_SIGN_ENABLED=false"

Write-Host "  DB_HOST: /cloudsql/$CLOUDSQL_CONN"

# --port=8080 matches the image's REGISTRY_PORT default; Cloud Run injects PORT
# with the same value, which the entrypoint normalizes back into REGISTRY_PORT.
# --no-allow-unauthenticated keeps the demo reachable only with a Cloud Run IAM
# identity token.
$deployResult = gcloud run deploy "${SERVICE_NAME}" `
  --source=. `
  --region="$env:GCP_REGION" `
  --platform=managed `
  --no-allow-unauthenticated `
  --set-secrets="DB_PASSWORD=${SECRET_ID}:latest" `
  --memory="512Mi" `
  --cpu="1" `
  --max-instances="10" `
  --concurrency=80 `
  --timeout=300 `
  --port=8080 `
  --service-account="${SA_EMAIL}" `
  --add-cloudsql-instances="${CLOUDSQL_CONN}" `
  --set-env-vars="$envVars" `
  --project="$env:GCP_PROJECT_ID"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "===================================================================="
    Write-Host "  DEPLOYMENT FAILED!"
    Write-Host "===================================================================="
    Write-Host ""
    Write-Host "  Check the build logs in the GCP Console:"
    Write-Host "    https://console.cloud.google.com/cloud-build/builds?project=$env:GCP_PROJECT_ID"
    Write-Host ""
    Write-Host "  Then re-run: .\deploy-all.ps1"
    Write-Host "===================================================================="
    exit 1
}

# ── Result ───────────────────────────────────────────────────────────────────
$SERVICE_URL = gcloud run services describe "${SERVICE_NAME}" --region="$env:GCP_REGION" --format="value(status.url)" --project="$env:GCP_PROJECT_ID"

Write-Host ""
Write-Host "===================================================================="
Write-Host "  DEPLOYMENT SUCCESSFUL!"
Write-Host "===================================================================="
Write-Host ""
Write-Host "  Service URL: ${SERVICE_URL}"
Write-Host ""
Write-Host "  Verify it works:"
Write-Host '    Invoke using an authorized Cloud Run IAM identity token; anonymous access is disabled.'
Write-Host ""
Write-Host "  API endpoints:"
Write-Host "    POST   ${SERVICE_URL}/rest/v1/registry-center/agent-cards"
Write-Host "    GET    ${SERVICE_URL}/rest/v1/registry-center/agent-cards"
Write-Host "    GET    ${SERVICE_URL}/rest/v1/registry-center/agent-cards/{org}/{name}"
Write-Host "    PUT    ${SERVICE_URL}/rest/v1/registry-center/agent-cards/{org}/{name}"
Write-Host "    DELETE ${SERVICE_URL}/rest/v1/registry-center/agent-cards/{org}/{name}"
Write-Host ""
Write-Host "  To update the service later, just run:"
Write-Host "    .\deploy-all.ps1"
Write-Host "  (it will skip already-created resources and re-deploy)"
Write-Host "===================================================================="
