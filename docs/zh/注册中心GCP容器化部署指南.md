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

# Registry Center - Google Cloud Platform 容器化部署指南

本指南帮你**一步一步**把这个注册中心服务部署到 Google Cloud Platform，无需任何技术背景。

---

## 前置条件

你需要一个 **Google Cloud 账号**（用 Gmail 注册即可），并且开通一个 **GCP 项目**并启用结算。

> 新用户有 $300 免费额度，运行这个服务每天大约 $1-2（最便宜配置 (~$0.06/小时)）。

### 如何创建 GCP 项目？（如果还没有）

1. 浏览器打开 https://console.cloud.google.com
2. 登录你的 Gmail 账号
3. 顶部点 **"选择项目"** → **"新建项目"**
4. 项目名称随便填（比如 `openan-proj`），点 **"创建"**
5. 创建完成后，在左侧菜单 **"结算"** → 关联结算账号（需要绑定信用卡或 PayPal）
6. **记下你的项目 ID**（GCP 会自动在名称后追加数字，格式类似 `openan-proj-123456`）

---

## 部署步骤（只需 3 步）

### 第 1 步：安装 gcloud CLI

打开 PowerShell（右键开始菜单 → "Windows PowerShell" 或 "终端"），复制下面整段命令回车：

```powershell
(New-Object Net.WebClient).DownloadFile("https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe", "$env:TEMP\gcloud-installer.exe"); Start-Process "$env:TEMP\gcloud-installer.exe" -Wait
```

安装过程中：
- 全部默认选项，一路 **Next**
- **勾选** "安装完成后启动 shell" 或 "Run gcloud init" 的选项
- 如果弹出命令行窗口要求登录，用你的 Gmail 账号登录，选择刚才创建的项目

> 装完后 **关掉当前 PowerShell，重新打开一个新的**。

---

### 第 2 步：检查登录状态

在新开的 PowerShell 中执行：

```powershell
gcloud auth list
```

如果你看到你的 Gmail 账号显示出来，说明登录成功了。

如果没登录，执行 `gcloud auth login`，会弹浏览器让你登录。

---

### 第 3 步：进入项目目录并一键部署

```powershell
cd 项目目录路径
.\deploy-all.ps1
```

> 把 `项目目录路径` 替换为你解压后 `registry-center` 文件夹的实际路径。例如：
> ```powershell
> cd C:\Users\<YourUsername>\Desktop\registry-center
> ```

运行后会提示你输入：
1. **GCP Project ID** — 就是前面创建项目时记下的那个 ID
2. **数据库密码** — 随便设一个，或者直接回车让系统自动生成

然后脚本会全自动完成：
- ✓ 创建数据库（Cloud SQL PostgreSQL）
- ✓ 构建 Docker 镜像
- ✓ 部署到 Cloud Run


**提示**：如果非首次部署，在创建数据库阶段出现ALREADY_EXISTS的报错时，这是正常的，不用进行任何操作。
![alt text](./images/db_already_exists_fig.png)

**全程大约 10-15 分钟**，看到 `DEPLOYMENT SUCCESSFUL!` 就成功了。

![alt text](./images/deploy_success_fig.png)
---

## 验证部署

脚本最后会输出一个 `https://xxxxx.run.app` 的地址，这是你的服务 URL。

在浏览器打开 `https://xxxxx.run.app/rest/v1/registry-center/agent-cards`，如果看到 `{"agentCards":[]}` 就说明服务正常运行（空列表表示还没注册过 Agent）。

或者用 PowerShell 测试：

```powershell
Invoke-RestMethod -Uri "https://xxxxx.run.app/rest/v1/registry-center/agent-cards"
```

---

## API 接口

部署成功后你可以通过以下接口管理 Agent 卡片：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/rest/v1/registry-center/agent-cards` | 注册 Agent |
| `GET` | `/rest/v1/registry-center/agent-cards` | 查询 Agent |
| `GET` | `/rest/v1/registry-center/agent-cards/{org}/{name}` | 获取单个 Agent |
| `PUT` | `/rest/v1/registry-center/agent-cards/{org}/{name}` | 更新 Agent |
| `DELETE` | `/rest/v1/registry-center/agent-cards/{org}/{name}` | 注销 Agent |

示例（注册一个 Agent）：

```powershell
$body = @{
    name = "my-agent"
    description = "A test agent"
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://xxxxx.run.app/rest/v1/registry-center/agent-cards" -Method Post -Body $body -ContentType "application/json"
```

---

## 常见问题

**Q: 脚本报错 "gcloud not found"？**

关掉 PowerShell 重新打开。如果还不行，说明 gcloud 没装好，回到第 1 步。

**Q: 看到 "API has not been used" 错误？**

等 1-2 分钟再运行 `.\deploy-all.ps1`，有些 API 启用需要时间。

**Q: 部署失败怎么重试？**

直接再跑一次 `.\deploy-all.ps1` 就行，已创建的资源会被自动跳过。

**Q: 如何更新服务？**

修改代码后，再跑一次 `.\deploy-all.ps1` 即可更新。

**Q: 如何关掉服务？**

```powershell
gcloud run services delete registry-center --region=asia-east1
gcloud sql instances delete registry-center-db
```

**Q: 费用大概多少？**

- Cloud Run：无请求时不收费。按请求计费。
- Cloud SQL（db-f1-micro）：约 $0.015/小时。

不使用时删除 Cloud SQL 实例即可节省费用，数据需要提前备份。
