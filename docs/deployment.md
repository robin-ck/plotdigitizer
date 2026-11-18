# Deploying the web interface

The app is one Python process (uvicorn) that starts worker subprocesses for
PDF work. It keeps all state on disk under `PD_DATA_ROOT`, so a restart loses
nothing but requests in flight. Run a single instance: rate limits, the job
cap and per-session locks live in memory.

## Install

```bash
python3 -m venv /opt/plotdigitizer/venv
/opt/plotdigitizer/venv/bin/pip install '/path/to/plotdigitizer[web]'
```

## Run (systemd)

```ini
# /etc/systemd/system/plotdigitizer.service
[Unit]
Description=plotdigitizer web interface
After=network.target

[Service]
User=plotdigitizer
Environment=PD_DATA_ROOT=/var/lib/plotdigitizer
Environment=PD_TRUSTED_PROXY=127.0.0.1
Environment=PD_MAX_UPLOAD_MB=50
Environment=PD_DISK_CAP_GB=10
ExecStart=/opt/plotdigitizer/venv/bin/uvicorn plotdigitizer.web.app:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Use a dedicated user with write access only to `PD_DATA_ROOT`.

## Reverse proxy (nginx)

```nginx
server {
    server_name digitizer.example.org;
    client_max_body_size 50m;          # keep in line with PD_MAX_UPLOAD_MB
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 120s;       # >= PD_JOB_TIMEOUT_S
    }
    # TLS via certbot or similar; serve HTTPS only, the session link is the key
}
```

`PD_TRUSTED_PROXY` must be the proxy's address as uvicorn sees it
(`127.0.0.1` above); only then is `X-Forwarded-For` used for rate limits.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `PD_DATA_ROOT` | `./pd-data` | sessions on disk |
| `PD_RETENTION_DAYS` | 7 | whole session deleted after this |
| `PD_MAX_UPLOAD_MB` | 50 | upload size limit |
| `PD_MAX_PAGES` | 100 | page limit per PDF |
| `PD_JOB_TIMEOUT_S` | 60 | hard timeout per worker job |
| `PD_MAX_JOBS` | 2 | concurrent worker jobs (about one per CPU core) |
| `PD_DISK_CAP_GB` | 10 | uploads refused above this total |
| `PD_UPLOADS_PER_HOUR` | 20 | per client IP |
| `PD_JOBS_PER_10MIN` | 600 | detect/extract/edit/render requests per client IP |
| `PD_TRUSTED_PROXY` | (none) | address of the reverse proxy |

## Notes

- Expired sessions are deleted hourly and on access.
- Uploaded PDFs are parsed by PyMuPDF in short-lived child processes with a
  hard timeout; still, keep PyMuPDF updated.
- Uploaded papers are private to their session link but stored for up to the
  retention period; state this on any page that links to the tool.
