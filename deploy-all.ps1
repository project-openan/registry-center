# =============================================================================
# Registry Center - One-Click GCP Deployment
# =============================================================================
# This script handles EVERYTHING:
#   1. Checks prerequisites (gcloud installed, logged in)
#   2. Creates GCP resources (Cloud SQL, Artifact Registry, etc.) if needed
#   3. Builds and deploys to Cloud Run
#
# USAGE:  Just run this script in PowerShell:
#   .\deploy-all.ps1
#
# You will be prompted for your GCP Project ID and a database password.
# =============================================================================

$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false
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

if (-not $env:GCP_REGION) { $env:GCP_REGION = "asia-east1" }
if (-not $env:DB_PASSWORD) {
    # Try to retrieve existing password from Secret Manager
    $secretId = "registry-center-db-password"
    $existingPassword = gcloud secrets versions access latest --secret="${secretId}" --project="$env:GCP_PROJECT_ID" 2>$null
    if ($existingPassword) {
        $env:DB_PASSWORD = $existingPassword
        Write-Host "  Using existing password from Secret Manager"
    } else {
        $env:DB_PASSWORD = Read-Host "Set a password for the PostgreSQL database (or press Enter to auto-generate)"
        if (-not $env:DB_PASSWORD) {
            $env:DB_PASSWORD = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object {[char]$_})
            Write-Host "  Auto-generated password: $env:DB_PASSWORD"
        }
    }
}

Write-Host ""
Write-Host "  Configuration:"
Write-Host "    Project ID : $env:GCP_PROJECT_ID"
Write-Host "    Region     : $env:GCP_REGION"
Write-Host ""

# ── Step 4: Setup GCP resources (idempotent - safe to re-run) ───────────────
Write-Host "[4/5] Setting up GCP resources (this may take 5-10 minutes)..."
Write-Host ""

$SERVICE_NAME    = "registry-center"
$ARTIFACT_REPO   = "registry-center"
$CLOUDSQL_INST   = "registry-center-db"
$DB_NAME         = "registry_center"
$DB_USER         = "registry"
$SA_NAME         = "registry-center-sa"
$SA_EMAIL        = "${SA_NAME}@$env:GCP_PROJECT_ID.iam.gserviceaccount.com"
$SECRET_ID       = "${SERVICE_NAME}-db-password"
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
Write-Host "  Storing DB password in Secret Manager..."
$secretExists = gcloud secrets describe "${SECRET_ID}" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null; $secretExists = ($LASTEXITCODE -eq 0)
if (-not $secretExists) {
    [System.Text.Encoding]::UTF8.GetBytes($env:DB_PASSWORD) | gcloud secrets create "${SECRET_ID}" --data-file=- --replication-policy="automatic" --project="$env:GCP_PROJECT_ID" 2>&1 | Out-Null
} else {
    Write-Host "    Secret already exists, skipping."
}

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
$envVars = "PERSISTENCE_MODE=postgresql"
$envVars += ",DB_HOST=/cloudsql/$CLOUDSQL_CONN"
$envVars += ",DB_PORT=5432"
$envVars += ",DB_NAME=$DB_NAME"
$envVars += ",DB_USERNAME=$DB_USER"
$envVars += ",DB_PASSWORD=$env:DB_PASSWORD"
$envVars += ",DB_POOL_MIN=2"
$envVars += ",DB_POOL_MAX=10"
$envVars += ",REGISTRY_ENABLE_HTTPS=false"
$envVars += ",REGISTRY_FORWARDED_ALLOW_IPS=*"
$envVars += ",REGISTRY_OWNER__VALIDATION__MODE=relaxed"

Write-Host "  DB_HOST: /cloudsql/$CLOUDSQL_CONN"

$deployResult = gcloud run deploy "${SERVICE_NAME}" `
  --source=. `
  --region="$env:GCP_REGION" `
  --platform=managed `
  --allow-unauthenticated `
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
Write-Host "    curl ${SERVICE_URL}/rest/v1/registry-center/agent-cards"
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
