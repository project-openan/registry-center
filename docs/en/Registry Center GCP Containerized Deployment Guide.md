<!--
Copyright (c) 2026 Huawei Technologies Co., Ltd.
All Rights Reserved.

SPDX-License-Identifier: Apache-2.0

   Licensed under the Apache License, Version 2.0 (the "License"); you may
   not use this file except in compliance with the License. You may obtain
   a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
   License for the specific language governing permissions and limitations
   under the License.
-->

# Registry Center - Google Cloud Platform Containerized Deployment Guide

This guide walks you through deploying the Registry Center service to Google Cloud Platform **step by step** — no technical background required.

---

## Prerequisites

You need a **Google Cloud account** (sign up with Gmail) with a **GCP project** that has billing enabled.

> New users get $300 in free credits. Running this service costs approximately $1–2 per day with the minimum configuration (~$0.06/hour).

### How to Create a GCP Project (If You Don't Have One)

1. Open your browser and go to https://console.cloud.google.com
2. Sign in with your Gmail account
3. At the top, click **"Select Project"** → **"New Project"**
4. Enter any project name (e.g., `openan-proj`) and click **"Create"**
5. After creation, go to **"Billing"** in the left menu → link a billing account (requires a credit card or PayPal)
6. **Note down your Project ID** (GCP appends a number to your project name, format: `openan-proj-123456`)

---

## Deployment Steps (Only 3 Steps)

### Step 1: Install gcloud CLI

Open PowerShell (right-click Start → "Windows PowerShell" or "Terminal") and paste the following command:

```powershell
(New-Object Net.WebClient).DownloadFile("https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe", "$env:TEMP\gcloud-installer.exe"); Start-Process "$env:TEMP\gcloud-installer.exe" -Wait
```

During installation:
- Keep all default options, click **Next** through everything
- **Check** the option "Start shell after installation" or "Run gcloud init"
- If a command line window prompts you to sign in, use your Gmail account and select the project you created

> After installation, **close your current PowerShell window and open a new one**.

---

### Step 2: Verify Login Status

In the new PowerShell window, run:

```powershell
gcloud auth list
```

If your Gmail account appears, you're logged in.

If not, run `gcloud auth login` — a browser window will open for you to sign in.

---

### Step 3: Navigate to the Project Directory and Deploy

Open PowerShell (right-click Start → "Windows PowerShell" or "Terminal"), then run:

```powershell
cd <project-directory-path>
.\deploy-all.ps1
```

> Replace `<project-directory-path>` with the actual path to the `registry-center` folder. For example:
> ```powershell
> cd C:\Users\YourUsername\Desktop\registry-center
> ```

> **If running `.\deploy-all.ps1` fails with the error** "File ... cannot be loaded. The file ... is not digitally signed. You cannot run this script on the current system." / "UnauthorizedAccess", this is caused by PowerShell's Execution Policy, which by default blocks unsigned scripts. Choose one of the following solutions:
> - **Option 1 (Recommended, permanent)**: Loosen the execution policy for your user account. Local scripts can run directly; only scripts downloaded from the internet require a signature.
>   ```powershell
>   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
>   ```
>   Then run `.\deploy-all.ps1` again.
> - **Option 2 (one-time only)**: Bypass the execution policy for a single run without changing system settings.
>   ```powershell
>   powershell -ExecutionPolicy Bypass -File .\deploy-all.ps1
>   ```

You will be prompted to enter:
1. **GCP Project ID** — the ID you noted down when creating your project
2. **Database Password** — set any password, or press Enter to auto-generate one

The script will then automatically:
- ✓ Create a Cloud SQL PostgreSQL database
- ✓ Build the Docker image
- ✓ Deploy to Cloud Run

**Note**: If this is not your first deployment, you may see `ALREADY_EXISTS` errors during the database creation phase. This is normal — no action is needed.
![alt text](./images/db_already_exists_fig.png)

**The entire process takes approximately 10–15 minutes**. Once you see `DEPLOYMENT SUCCESSFUL!`, you're done.

![alt text](./images/deploy_success_fig.png)

---

## Verifying the Deployment

The script outputs a `https://xxxxx.run.app` URL at the end — this is your service URL.

Open `https://xxxxx.run.app/rest/v1/registry-center/agent-cards` in your browser. If you see `{"agentCards":[]}`, the service is running normally (an empty list means no agents have been registered yet).

Alternatively, test with PowerShell:

```powershell
Invoke-RestMethod -Uri "https://xxxxx.run.app/rest/v1/registry-center/agent-cards"
```

---

## API Endpoints

Once deployed, you can manage Agent Cards through the following endpoints:

| Method   | Path                                                    | Description         |
|----------|---------------------------------------------------------|---------------------|
| `POST`   | `/rest/v1/registry-center/agent-cards`                  | Register an Agent   |
| `GET`    | `/rest/v1/registry-center/agent-cards`                  | Query Agents        |
| `GET`    | `/rest/v1/registry-center/agent-cards/{org}/{name}`     | Get a single Agent  |
| `PUT`    | `/rest/v1/registry-center/agent-cards/{org}/{name}`     | Update an Agent     |
| `DELETE` | `/rest/v1/registry-center/agent-cards/{org}/{name}`     | Deregister an Agent |

Example (registering an Agent):

```powershell
$body = @{
    name = "my-agent"
    description = "A test agent"
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://xxxxx.run.app/rest/v1/registry-center/agent-cards" -Method Post -Body $body -ContentType "application/json"
```

---

## FAQ

**Q: I see "gcloud not found" error?**

Close PowerShell and reopen it. If it still doesn't work, gcloud isn't installed properly — go back to Step 1.

**Q: I see "API has not been used" error?**

Wait 1–2 minutes and run `.\deploy-all.ps1` again. Some APIs take time to activate.

**Q: The deployment failed. How do I retry?**

Simply run `.\deploy-all.ps1` again. Already-created resources will be automatically skipped.

**Q: How do I update the service?**

After making code changes, run `.\deploy-all.ps1` again to update.

**Q: How do I shut down the service (to save costs)?**

```powershell
gcloud run services delete registry-center --region=asia-east1
gcloud sql instances delete registry-center-db
```

**Q: What is the estimated cost?**

- **Cloud Run**: No cost when idle. Pay per request.
- **Cloud SQL (db-f1-micro)**: Approximately $0.015/hour.

To save costs, delete the Cloud SQL instance when not in use. Back up your data beforehand if needed.
