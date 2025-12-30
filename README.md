# Fortigate Backup Automation

Automated solution to backup Fortigate configurations via API (HTTPS) using Docker. Includes a Web Interface (FileBrowser) to retrieve backups easily.

## Features
*   **Pull Strategy**: connects to Fortigates via API (HTTPS), no inbound ports required on the server.
*   **Token Authentication**: Supports global or per-device API tokens for secure access.
*   **Encryption**: Optional AES encryption for downloaded backup files (password protected).
*   **Web UI**: Browse and download `.conf` files via web browser (FileBrowser).
*   **Secure**: Supports Read-Only credentials, encrypted secrets (via .env), and secure API connection.
*   **Automated**: Supports scheduled daily runs or manual execution.
*   **CI/CD**: Includes GitHub Actions workflow for **Self-Hosted Runners** (ideal for private networks).

## Quick Start (Local)

1.  **Clone the repo**:
    ```bash
    git clone <your-repo-url>
    cd Forti-bkp-script
    ```

2.  **Configure**:
    *   Copy the template: `cp .env.example .env`
    *   Edit `.env` with your credentials/tokens.
    *   Add your device IPs to `config/devices.txt`.

3.  **Run**:
    ```bash
    docker compose -f fortigate-api-git-backups.yml up -d --build
    ```

4.  **Access**:
    *   Web File Browser: `http://localhost:8080` (Default: `admin` / `admin`).

## Configuration Persistence (Important)
Since the CI/CD pipeline refreshes the code on every deploy, manual changes to files on the server (like `.env`) might be overwritten.
*   **To change configuration permanently**: Edit `.env.example` in this repository and push the changes.
*   **To change secrets**: Update them in GitHub Repository Settings.

## Configuration (Reference)

### Environment Variables (`.env`)
```bash
# Authentication (Token Required)
# Authentication (Token Required)
FORTIGATE_API_TOKEN=your_token_here (Global)
# Or define per-device tokens (see Secrets section below)

# Encryption
ENCRYPT_BACKUP=yes
BACKUP_ENCRYPTION_KEY=mysecretpassword

# Connection
FGT_PORT=33443
FGT_PROTOCOL=https

# Storage
HOST_BACKUP_DIR=./backups  # Local folder to store files

# Automation Settings
RUN_MODE=manual  # 'manual' (run once) or 'schedule' (daily loop)
SCHEDULE_TIME=03:00
```

### Devices (`config/devices.txt`)
List your Fortigate IP addresses, one per line. You can optionally add a name after a comma.
Format: `IP:PORT, Device Name`
```text
192.168.1.1, Main-Firewall      
10.0.0.254:8443, Branch-Office   
172.20.202.1:33443, Lab-Fortigate
```

## Deployment on Private Server (Ubuntu)

This project is configured for **GitHub Self-Hosted Runners**, allowing you to deploy to a private server without opening inbound ports.

### 1. Server Setup
1.  Install Docker & Git on your Ubuntu server.
2.  Install the **GitHub Actions Runner** (Repo Settings -> Actions -> Runners -> New self-hosted runner).
3.  **Important**: Install the runner as a service so it persists (`sudo ./svc.sh install`).

> [!TIP]
> **Corporate Recommendation: Runner Groups**
> If you are using a GitHub Enterprise or Organization account, it is highly recommended to use **Runner Groups** to manage access and security at scale.
> 1.  In your Organization Settings, go to **Actions > Runner groups**.
> 2.  Create a group (e.g., `Production-Security`) and add your specific self-hosted runners to it.
> 3.  Restrict which repositories can use this group to prevent unauthorized usage of your internal infrastructure.
> 4.  Update your workflow `.yml` from `runs-on: self-hosted` to `runs-on: { group: 'Production-Security' }`.

### 2. Secrets (GitHub)
Go to **Settings > Secrets and variables > Actions** and create:
*   `FORTIGATE_API_TOKEN` (Primary Auth)
*   `ENCRYPT_BACKUP` (Set to `yes` to enable encryption)
*   `BACKUP_ENCRYPTION_KEY` (Password for encrypted backups)
*   `DOCKER_SUBNET` (Custom subnet for Docker network, e.g., `10.244.0.0/24`)

### Auto-Push to Git (Optional)
To enable automatic committing of backups:
1.  Enable `GIT_REPO_URL` in `.env` (e.g., `https://github.com/user/repo.git`).
2.  Provide `GIT_PUSH_TOKEN` (Personal Access Token) in Secrets.
3.  Backups will be saved in `backups/[device_name]/` and pushed.
```bash
GIT_REPO_URL=https://github.com/myorg/mybackuprepo.git
GIT_PUSH_TOKEN=ghp_xxxxxxxxx (Mapped from GIT_PUSH_TOKEN secret)
GIT_USER_NAME=BackupBot
GIT_USER_EMAIL=bot@backup.local
```
#
#### Advanced: Per-Device Tokens
If you have multiple devices and need different tokens for each, you can define them using the following conventions:

**1. By Name (Recommended)**
Use the name specified in `devices.txt`. Spaces are replaced by underscores.
*   **Example in `devices.txt`**: `192.168.1.1, Main-Firewall`
*   **Env Var / Secret**: `FORTIGATE_API_TOKEN_Main-Firewall`

**2. By IP (Fallback)**
If no name is provided, use the IP with dots replaced by underscores.
*   **Example in `devices.txt`**: `10.0.0.1`
*   **Env Var / Secret**: `FORTIGATE_API_TOKEN_10_0_0_1`

> [!IMPORTANT]
> **GitHub Secrets Mapping**: When adding a new per-device token in GitHub Secrets, you **must also add it** to the `Configure .env from Secrets` step in `.github/workflows/fortigate-api-git-backups.yml` so it gets passed to the runner.

### 3. Deploy
Just push to the `main` branch. The runner will pick up changes, pull the code, and restart the containers automatically



