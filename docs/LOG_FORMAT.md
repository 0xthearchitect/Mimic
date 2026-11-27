# MIMIC log format

Every service writes [JSON Lines](https://jsonlines.org/): one JSON object per
line, one file per service, in `logs/`:

```
logs/
├── ssh_honeypot.jsonl
├── ftp_honeypot.jsonl
├── telnet_honeypot.jsonl
├── http_honeypot.jsonl
└── mysql_honeypot.jsonl
```

## Common fields

Every event, from every service, has these fields:

| Field       | Type   | Example                      | Notes                              |
|-------------|--------|------------------------------|------------------------------------|
| `timestamp` | string | `2026-11-27T10:10:50.928Z`   | ISO 8601, **UTC**, milliseconds    |
| `event`     | string | `login_attempt`              | One of the events below            |
| `service`   | string | `ssh`                        | `ssh`, `ftp`, `telnet`, `http`, `mysql` |
| `port`      | int    | `22`                         | Port the honeypot listened on      |
| `client_ip` | string | `203.0.113.7`                | Attacker address                   |

## Events

### `connection`
A client connected.
`connection_number` (int, per service, since start) — not on SSH.

### `blocked_connection` (SSH)
Connection refused by the security layer. `reason` (string).

### `login_attempt`
Credentials offered by the client — the same shape for SSH, FTP and Telnet.

| Field       | Type          | Notes                                           |
|-------------|---------------|-------------------------------------------------|
| `username`  | string        | Exactly as sent                                 |
| `password`  | string / null | Exactly as sent; `null` for FTP anonymous login |
| `success`   | bool          | Whether the honeypot let them in                |

Service extras: SSH adds `valid_credentials` and `any_auth_mode`; FTP adds
`anonymous: true` for anonymous logins. Telnet always has `success: false`
(it only harvests credentials).

### `command`
Something the client sent. `command` (string). SSH and FTP add `username`.
For HTTP this is the request line (`GET /admin HTTP/1.1`); for MySQL the query.
FTP `PASS` lines are **not** logged as commands — they appear only in
`login_attempt`.

### `file_upload` (FTP)
A file was captured. **Treat it as malware.**

| Field        | Type   | Notes                                 |
|--------------|--------|---------------------------------------|
| `username`   | string |                                       |
| `filename`   | string | Sanitised name it was stored under    |
| `size`       | int    | Bytes                                 |
| `sha256`     | string | Hash of the stored file               |
| `saved_path` | string | Absolute path inside `ftp_storage/`   |

## Example: all logins from every service

```bash
cat logs/*_honeypot.jsonl | jq -c 'select(.event == "login_attempt")
  | {timestamp, service, client_ip, username, password, success}'
```

## Changes from v1.1.x

Before this format, FTP/HTTP/MySQL/Telnet used `event_type` and `source_ip`,
logged credentials as command text (`"PASS 123456"`, `"PASSWORD: x"`), and
timestamps were local time. FTP upload hashes were also wrong (they hashed an
empty file). SSH events keep their previous field names.
