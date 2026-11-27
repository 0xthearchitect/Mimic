<div align="center">
  <img src="assets/mimic_banner.png" alt="Mimic: every port is a mask" width="100%" />
  <h1>MIMIC Honeypot Framework (BETA)</h1>
</div>

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey.svg)

**On stage, everyone thinks they're the star. But the only thing they are, is the show.**

*Every port is a mask. The audience is watching.*

</div>

<p align="center">
  <img src="assets/mimic_logo_animation.gif" width="96" alt="The hand-drawn Mimic mask, glitching" />
</p>

---

## Features

### Service Emulation
- **SSH** - Full interactive shell with realistic filesystem
- **FTP** - File transfer protocol emulation
- **HTTP** - Web server honeypot
- **Telnet** - Legacy protocol support
- **MySQL** - Database service emulation
- **RDP** - Remote Desktop Protocol (planned)

### Security Features
- **Credential Harvesting** - Capture usernames and passwords
- **Session Logging** - JSON-formatted logs for analysis
- **Human Behavior Simulation** - Realistic response delays
- **Customizable Authentication** - Accept any credentials or enforce specific ones
- **Port Flexibility** - Configure any port for any service

### Advanced Capabilities
- **Multi-OS Simulation** - Convincing banners for different operating systems
- **Interactive Shell** - Command execution and file exploration
- **Filesystem Virtualization** - Realistic directory structures
- **Command Logging** - Track every attacker action
- **IP Tracking** - Monitor connection sources

---

## ⚠️ Before You Deploy

A honeypot exists to be attacked. Treat the machine running MIMIC as hostile ground:

- **Isolate it.** Run MIMIC in a dedicated VM or container, never on a machine with personal data, credentials or access to your internal network.
- **Don't run as root/Administrator** unless you need ports below 1024 — on Linux prefer `setcap` (see [PLATFORMS.md](PLATFORMS.md)).
- **Treat captured files as malware.** Everything in `ftp_storage/` was uploaded by attackers. Don't open or execute it on the host.
- **Logs contain attacker data** (credentials, commands, IPs). They are git-ignored on purpose; don't publish them unredacted.

---

## Quick Start

### Prerequisites

**Windows:**
```bash
# Python 3.11 or higher
python --version

# Install dependencies
pip install -r requirements.txt
```

**Linux/Ubuntu:**
```bash
# Python 3.11 or higher
python3 --version


# Or manual installation
sudo apt-get update
sudo apt-get install python3 python3-pip python3-pygame
sudo pip3 install pyyaml asyncssh pygame

# For ports below 1024, you'll need root privileges
sudo python3 mimic.py
```

### Installation

**Windows:**
```bash
Download of the last Mimic release

OR

# Clone the repository
git clone https://github.com/Samucahub/mimic.git

After:
cd mimic

# Install dependencies
pip install -r requirements.txt
```

**Ubuntu/Linux:**
```bash
Download of the last Mimic release

OR

# Clone the repository
git clone https://github.com/Samucahub/mimic.git

After:
cd mimic

sudo pip3 install -r requirements.txt
```

### Running MIMIC

#### Option 1: Web dashboard (Recommended)

```bash
python main.py --dashboard
```

MIMIC prints a private link (`http://127.0.0.1:8787/?token=…`). Open it in your browser:

- **Playbill**: set the fake identity, house rules and services, then **Let the show begin**.
- **The Stage**: live activity. *The script* tells each visit as a scene; *the house* seats every visitor by how deep they got (front row = got in and acted, back = refused or only knocked). Pick a seat to read their ticket, export their events or **show them out** (block the IP on every service).
- **Lost & Found**: files left behind (SHA-256, who, how often) and the most-tried passwords.

The dashboard only listens on this machine. From another computer, use an SSH tunnel:
`ssh -L 8787:127.0.0.1:8787 you@honeypot-host`. The link changes every time MIMIC starts.
Why it is built this way: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

#### Option 1b: Legacy visual configurator (pygame)

**Windows:**
```bash
python mimic.py
```

**Linux:**
```bash
# Normal ports (>1024)
python3 mimic.py

# For privileged ports (21, 22, 23, 80)
sudo python3 mimic.py

# Or use the startup script
chmod +x start_mimic.sh
./start_mimic.sh
```

1. Configure identity (username, password, hostname)
2. Select OS template (Ubuntu, Debian, CentOS, Windows, Kali)
3. Enable desired services (SSH, FTP, HTTP, etc.)
4. Set honeypot mode (accept any credentials or enforce specific ones)
5. Click **"Let the show begin!"**
6. Monitor live activity
7. Click **"Close the curtains"** to stop

#### Option 2: Headless (servers, no GUI)

```bash
# First run creates config/honeypot.yaml from config/honeypot.example.yaml
python main.py

# Or point to another config file
python main.py --config path/to/honeypot.yaml
```

If the config has a mistake (bad port, unknown service type…), MIMIC lists every problem and exits before opening any port.

#### Option 3: Docker

```bash
cp config/honeypot.example.yaml config/honeypot.yaml   # then edit it
docker compose up -d --build
docker compose logs -f                                 # live activity
```

The container runs as a non-root user with a read-only filesystem and no extra capabilities. Logs and captured files live in Docker volumes (`docker compose cp mimic:/app/logs ./mimic-logs` to export them). Keep the `ports:` list in `docker-compose.yml` in sync with the services you enable.

> **Note:** FTP passive-mode transfers need the passive port range reachable from outside; under Docker's default bridge network, logins and commands are captured but file transfers may fail.

---

## Configuration

`config/honeypot.yaml` is your local config: it is written by the visual configurator and git-ignored (it may contain passwords). `config/honeypot.example.yaml` is the template.

### Example Configuration

```yaml
system:
  username: admin
  password: admin123
  hostname: web-server
  os_template: Ubuntu

options:
  any_auth: true
  brute_force_attempts: 3
  enable_logging: true
  human_patterns: false
  log_retention_days: 7
security:
  enabled: true
  ip_blocking:
    auto_block_failed_logins: 10
  rate_limits:
    block_duration_minutes: 60
    max_connections_per_minute: 60
    max_failed_logins: 10
    window_seconds: 60

services:
  '21':
    allow_download: false
    allow_upload: false
    anonymous_login: true
    banner: 220 ProFTPD 1.3.5 Server (Debian)
    enabled: true
    max_file_size: 104857600  #100 MB
    type: ftp
  '22':
    banner: SSH-2.0-OpenSSH_7.6p1 Ubuntu-4ubuntu0.3
    enabled: true
    type: ssh
  '23':
    enabled: true
    type: telnet
```

### OS Templates(Future)

| Template | Description | Banner |
|----------|-------------|--------|
| **Ubuntu** | Ubuntu 18.04.6 LTS | GNU/Linux 4.15.0-20-generic x86_64 |
| **Debian** | Debian 11 (bullseye) | Debian GNU/Linux 11 |
| **CentOS** | CentOS 7.9.2009 | CentOS Linux release 7.9.2009 (Core) |
| **Windows** | Windows Server 2019 | Microsoft Windows Server 2019 Standard |
| **Kali** | Kali Linux Rolling | Kali GNU/Linux Rolling |

---

## Usage Examples

### Honeypot Mode (Accept Any Credentials)

```yaml
options:
  any_auth: true
```

Attackers can login with **any** username/password combination. Perfect for capturing credential attempts.

### Authenticated Mode (Specific Credentials Only)

```yaml
options:
  any_auth: false
system:
  username: admin
  password: secret123
```

Only accepts the configured username and password. Rejects all others.

### Testing the Honeypot

```bash
# SSH Connection
ssh admin@192.168.1.100 -p 22

# FTP Connection
ftp 192.168.1.100 or Filezila

# Scan with Nmap
nmap -sV 192.168.1.100
```

---

## Monitoring & Logs

### Log Files

```
logs/
├── ssh_honeypot.jsonl      # One JSON Lines file per service,
├── ftp_honeypot.jsonl      #   all in the same format
├── telnet_honeypot.jsonl
├── http_honeypot.jsonl
├── mysql_honeypot.jsonl
└── honeypot_output.log     # Main system log (what the GUI shows)
```

### FTP Storage

All files sent via FTP end up in this folder storage.

```
ftp_storage/
└── home/             # Users in system
    ├── ftpuser       # User default in FTP service
    |   └── files/
    |
    └── $username/    # This file is named based on the configured username
        ├── Desktop/
        ├── Documents/
        |   └── notes.txt
        ├── ...
        └── welcome.txt
```

### Log Format (JSON Lines)

Every service uses the same fields, so you can analyse all of them together. Full reference: [docs/LOG_FORMAT.md](docs/LOG_FORMAT.md).

```json
{
  "timestamp": "2026-11-27T10:10:50.928Z",
  "event": "login_attempt",
  "service": "ssh",
  "port": 22,
  "client_ip": "192.168.1.50",
  "username": "admin",
  "password": "password123",
  "success": true
}
```

Events: `connection`, `login_attempt`, `command`, `file_upload` (with SHA-256), `blocked_connection`.

```bash
# Every login attempt, from every service
cat logs/*_honeypot.jsonl | jq -c 'select(.event == "login_attempt")'
```

---

## Development

### Project Structure

```
mimic/
├── main.py                     # Entry point (headless, or --dashboard)
├── mimic.py                    # Legacy pygame configurator
├── dashboard/
│   ├── server.py               # aiohttp app: API, live events, guards
│   ├── store.py                # SQLite index over the JSONL logs
│   └── static/                 # HTML, CSS, JS modules, vendored fonts
├── Dockerfile, docker-compose.yml
├── config/
│   ├── honeypot.example.yaml   # Template (versioned)
│   ├── honeypot.yaml           # Your config (git-ignored)
│   └── templates/              # OS templates (future)
├── core/
│   ├── controller.py           # Service registry + orchestration
│   ├── config_schema.py        # Config validation
│   ├── security_layer.py       # Rate limiting / IP blocking
│   └── service_emulator/
│       ├── base_service.py
│       ├── ssh_emulator.py
│       ├── ftp_emulator.py
│       └── ...
├── log_system/
│   └── events.py               # Unified JSON Lines event log
├── docs/LOG_FORMAT.md, docs/ARCHITECTURE.md
├── assets/brand/               # Logo kit + BRAND.md (rules and reasons)
├── tools/brand/                # Scripts that regenerate the logo kit
├── tests/
├── ftp_storage/                # Captured files (git-ignored)
└── logs/                       # Generated logs (git-ignored)
```

### Adding New Services

1. Create the emulator in `core/service_emulator/`, inheriting from `BaseService`
2. Implement `handle_connection()`; log with `log_connection`, `log_login`, `log_command`
3. Register it in `SERVICE_REGISTRY` in `core/controller.py`

### Running the Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -m 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Security

Found a security vulnerability? Please see [SECURITY.md](SECURITY.md) for reporting guidelines.

---

## :coffee: Buy Me a Coffee

<a href="https://www.buymeacoffee.com/samunana" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

## Follow Me

<p>
  <a href="https://x.com/CyberSamu_">
        <img src="https://img.shields.io/badge/X-000000?style=for-the-badge&logo=twitter&logoColor=white"/>
  </a>
  <a href="https://www.linkedin.com/in/samuel-rocha-3a630731a/">
        <img src="https://img.shields.io/static/v1?message=LinkedIn&logo=linkedin&label=&color=0077B5&logoColor=white&labelColor=&style=for-the-badge" height="35" alt="linkedin logo"  />
  </a>
</p>

## Acknowledgments

- To my mom who gave birth to me.
- **asyncssh** - Robust SSH protocol implementation
- **Pygame** - Visual interface framework
- Inspired by classic honeypot projects like Cowrie and Kippo

---

## Contact

**Author:** The Architect  
**GitHub:** [@thearchitect](https://github.com/0xthearchitect)  
**Project:** [MIMIC Honeypot](https://github.com/0xthearchitect/mimic)

---

<div align="center">

**🎭 The stage is set. The audience watches. 🎭**

*Let the show begin!*

</div>






























