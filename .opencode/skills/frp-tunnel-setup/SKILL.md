---
name: frp-tunnel-setup
description: Use when setting up or troubleshooting FRP tunnel (frps on VPS/Coolify + frpc on home Windows PC) to expose a local project via a public domain. Covers DNS, Coolify Docker Compose, Windows frpc install, scheduled task autostart, security (TLS, token, basic auth), firewall, and debugging. Activates on: FRP, frps, frpc, tunnel, reverse proxy, Coolify, expose localhost, домашний ПК, туннель, проброс, vhost, customDomains, 7000 port, frpc.exe, frps.toml, frpc.toml.
---

# FRP Tunnel Setup — VPS Coolify + Windows Home PC

> Publish a local project behind NAT/firewall via a VPS with Coolify using FRP (Fast Reverse Proxy).

## Architecture

```text
User -> https://ai.example.ru -> Coolify Proxy (VPS :443)
  -> frps container (internal :8080) -> TLS tunnel :7000
  -> frpc.exe (Windows) -> http://127.0.0.1:8000
```

- VPS runs `frps` in a Coolify Docker Compose resource.
- Home Windows runs `frpc.exe` as a scheduled task.
- Coolify handles `:80/:443`, FRP only occupies `:7000` (control) and `:8080` (internal HTTP).
- Home PC needs no white IP, no router port forwarding.

## Versions & Downloads

- **FRP v0.69.1** — use the same version on both sides.
- Docker images: `ghcr.io/fatedier/frps:v0.69.1` / `ghcr.io/fatedier/frpc:v0.69.1`
- Windows binary: `frp_0.69.1_windows_amd64.zip` from [GitHub Releases](https://github.com/fatedier/frp/releases)

---

## Step 1 — DNS

Create an A-record for the subdomain:

```
Type: A
Name: ai
Value: <VPS_IP>
TTL: 300
```

Verify: `nslookup ai.example.ru` → must resolve to VPS IP.

---

## Step 2 — VPS Firewall

Open only these ports:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 7000/tcp
```

**Do NOT expose** `8080`, `7500`, `7400`, `8000` to the internet.

---

## Step 3 — Generate FRP Token

```bash
openssl rand -hex 32
```

Save the output — it goes into both Coolify ENV and `frpc.toml`.

---

## Step 4 — Coolify: Docker Compose Resource

Create a new resource `frp-server` (type: Docker Compose).

### 4a. Environment Variable

Key: `FRP_TOKEN`, value: the hex token from Step 3.

### 4b. Docker Compose (preferred — configs.content)

```yaml
services:
  frps:
    image: ghcr.io/fatedier/frps:v0.69.1
    restart: unless-stopped
    command: ["-c", "/etc/frp/frps.toml"]
    environment:
      FRP_TOKEN: ${FRP_TOKEN}
    ports:
      - "7000:7000"
    expose:
      - "8080"
    configs:
      - source: frps_config
        target: /etc/frp/frps.toml

configs:
  frps_config:
    content: |
      bindPort = 7000
      vhostHTTPPort = 8080

      auth.method = "token"
      auth.token = "{{ .Envs.FRP_TOKEN }}"

      transport.tls.force = true
```

### 4c. Alternative (if configs.content not supported)

Create `/opt/frp/frps.toml` on VPS with token hardcoded:

```toml
bindPort = 7000
vhostHTTPPort = 8080

auth.method = "token"
auth.token = "<TOKEN_HERE>"

transport.tls.force = true
```

Then use volume mount:

```yaml
services:
  frps:
    image: ghcr.io/fatedier/frps:v0.69.1
    restart: unless-stopped
    command: ["-c", "/etc/frp/frps.toml"]
    ports:
      - "7000:7000"
    expose:
      - "8080"
    volumes:
      - /opt/frp/frps.toml:/etc/frp/frps.toml:ro
```

### 4d. Coolify Domain

Add to the `frp-server` resource:

```
https://ai.example.ru:8080
```

`:8080` is the **internal** container port — users never type it. Coolify proxies `:443` → container `:8080`.

---

## Step 5 — Install frpc on Windows

Run as Administrator in PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path C:\frp
Invoke-WebRequest -Uri "https://github.com/fatedier/frp/releases/download/v0.69.1/frp_0.69.1_windows_amd64.zip" -OutFile "$env:TEMP\frp.zip"
Expand-Archive -Path "$env:TEMP\frp.zip" -DestinationPath "$env:TEMP\frp" -Force
Copy-Item "$env:TEMP\frp\frp_0.69.1_windows_amd64\frpc.exe" -Destination "C:\frp\frpc.exe" -Force
C:\frp\frpc.exe --version
```

---

## Step 6 — frpc.toml

Create `C:\frp\frpc.toml`:

```toml
serverAddr = "<VPS_IP>"
serverPort = 7000

auth.method = "token"
auth.token = "<SAME_FRP_TOKEN>"

transport.tls.enable = true

[[proxies]]
name = "ai-project"
type = "http"
localIP = "127.0.0.1"
localPort = 8000
customDomains = ["ai.example.ru"]

httpUser = "test"
httpPassword = "StrongTestPassword-2026"

healthCheck.type = "http"
healthCheck.path = "/"
healthCheck.timeoutSeconds = 3
healthCheck.maxFailed = 3
healthCheck.intervalSeconds = 10
```

Replace: `<VPS_IP>`, `<SAME_FRP_TOKEN>`, `ai.example.ru`, `8000`, `test`, `StrongTestPassword-2026`.

- `localPort` must match your local project port (8000, 3000, 7860, etc.).
- `customDomains` must **exactly** match the domain users will use.
- `httpUser`/`httpPassword` add **Basic Auth** — keep during development.

---

## Step 7 — First Run & Verify

1. Confirm local project responds: `Invoke-WebRequest http://127.0.0.1:8000`
2. Confirm port 7000 reachable: `Test-NetConnection <VPS_IP> -Port 7000`
3. Run frpc manually:

```powershell
C:\frp\frpc.exe -c C:\frp\frpc.toml
```

Expected output:

```
login to server success
proxy added: ai-project
start proxy success
```

4. Open `https://ai.example.ru` — browser should prompt for Basic Auth credentials.

---

## Step 8 — Autostart (Scheduled Task)

Run as Administrator:

```powershell
$Action = New-ScheduledTaskAction -Execute "C:\frp\frpc.exe" -Argument "-c C:\frp\frpc.toml"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask -TaskName "FRP Client" -Action $Action -Trigger $Trigger -Principal $Principal
Start-ScheduledTask -TaskName "FRP Client"
```

Manage:

```powershell
Get-ScheduledTask -TaskName "FRP Client"
Start-ScheduledTask -TaskName "FRP Client"
Stop-ScheduledTask -TaskName "FRP Client"
Unregister-ScheduledTask -TaskName "FRP Client" -Confirm:$false
```

---

## Traffic Flow

| Layer | Protocol | Note |
|-------|----------|------|
| User → Coolify | HTTPS :443 | Coolify terminates TLS |
| Coolify → frps container | HTTP :8080 | Internal Docker network |
| frps → frpc | TCP/TLS :7000 | Token-authenticated TLS tunnel |
| frpc → local project | HTTP :8000 | Loopback, no encryption needed |

Real user IP arrives via `X-Forwarded-For` / `X-Real-IP` headers.

---

## Security Rules

1. **Token must be long** — 64 hex chars minimum. Never use short/guessable tokens.
2. **No dashboard on 0.0.0.0** — if needed, bind to `127.0.0.1` only and never expose port 7500.
3. **Local project listens on 127.0.0.1 only** — never bind to 0.0.0.0 on home PC.
4. **Keep Basic Auth during development** — protects from bots and accidental exposure.
5. **Do NOT open home port 8000 on router.**
6. **Never commit tokens to git.**

---

## Debugging Common Errors

| Symptom | Likely Cause | Check |
|---------|-------------|-------|
| `authorization failed` | Token mismatch | Same token in Coolify ENV and frpc.toml |
| `connect to server error` | Port 7000 closed or wrong IP | `Test-NetConnection <VPS_IP> -Port 7000` |
| 404 or blank page | frpc not connected / customDomains mismatch | Verify frpc logs, domain name exactly |
| Browser asks for password | Normal — Basic Auth working | Use configured httpUser/httpPassword |
| Tunnel dead after Windows reboot | Scheduled task not running | `Get-ScheduledTask -TaskName "FRP Client"` |
| Tunnel dead after VPS reboot | frps container stopped | Check Coolify Deployments / Logs |
| Antivirus deletes frpc.exe | False positive Riskware/HackTool | Add `C:\frp\frpc.exe` to AV exclusions |

---

## What NOT To Do

- Don't bind FRP to ports 80/443 (Coolify owns them).
- Don't expose port 8080, 7500, 8000 to the internet.
- Don't run frps on home PC (it goes on VPS).
- Don't use `localhost` as `serverAddr`.
- Don't mismatch domain across DNS, Coolify, and `customDomains`.
- Don't skip TLS on the control connection.
- Don't open the project to 0.0.0.0 at home.

---

## Minimal Config Recap

```
DNS:       ai.example.ru A <VPS_IP>
Coolify:   frps container, env FRP_TOKEN, domain https://ai.example.ru:8080
VPS:       ports 22, 80, 443, 7000 open
Windows:   C:\frp\frpc.exe + C:\frp\frpc.toml + scheduled task
frpc.toml: serverAddr, token, tls=true, proxy to 127.0.0.1:8000, customDomains
Verify:    login success → https://ai.example.ru prompts for password
```
