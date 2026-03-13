# Pattern Project — Daily Command Cheat Sheet

Server: `root@ubuntu-s-2vcpu-2gb-90gb-intel-nyc3-01`
Project: `/opt/pattern`

---

## Git

```bash
# Pull latest from main
cd /opt/pattern
git pull origin main

# Check status / recent history
git status
git log --oneline -10

# Stage, commit, push
git add -A
git commit -m "description of changes"
git push origin main

# Discard all local changes (careful!)
git checkout -- .

# See what changed since last commit
git diff
git diff --staged          # staged changes only

# Create and switch to a new branch
git checkout -b feature/my-branch
git push -u origin feature/my-branch
```

---

## Pattern Service (systemd)

```bash
# Start / stop / restart
systemctl start pattern
systemctl stop pattern
systemctl restart pattern

# Check if running
systemctl status pattern

# Enable on boot / disable
systemctl enable pattern
systemctl disable pattern
```

---

## Logs (journalctl)

```bash
# Follow live logs
journalctl -u pattern -f

# Last 200 lines
journalctl -u pattern -n 200

# Last 200 lines, no pager (straight to terminal)
journalctl -u pattern -n 200 --no-pager

# Logs since last boot
journalctl -u pattern -b

# Logs from today only
journalctl -u pattern --since today

# Logs from last hour
journalctl -u pattern --since "1 hour ago"

# Search logs for a keyword
journalctl -u pattern | grep "error"
```

---

## Server Power

```bash
# Reboot the server
reboot

# Shut down immediately
shutdown now

# Shut down in 10 minutes
shutdown +10

# Cancel a pending shutdown
shutdown -c
```

---

## Python / Virtualenv

```bash
cd /opt/pattern

# Activate the virtualenv
source venv/bin/activate

# Run the app manually (web UI mode, default)
python main.py

# Run in CLI mode
python main.py --cli

# Run in dev mode (debug tools)
python main.py --dev

# Install / update dependencies
pip install -r requirements.txt
pip install -r requirements.txt --upgrade

# Check installed packages
pip list
pip freeze
```

---

## PostgreSQL

```bash
# Service control
systemctl start postgresql
systemctl stop postgresql
systemctl restart postgresql
systemctl status postgresql

# Open psql shell
sudo -u postgres psql

# Common psql commands (inside psql):
#   \l              list databases
#   \c dbname       connect to database
#   \dt             list tables
#   \q              quit
```

---

## Redis

```bash
# Service control
systemctl start redis-server
systemctl stop redis-server
systemctl restart redis-server
systemctl status redis-server

# Quick connectivity test
redis-cli ping              # should reply PONG

# Open Redis CLI
redis-cli
```

---

## Nginx

```bash
# Test config before reloading
nginx -t

# Reload config (no downtime)
systemctl reload nginx

# Restart fully
systemctl restart nginx

# View error log
tail -100 /var/log/nginx/error.log

# View access log
tail -100 /var/log/nginx/access.log
```

---

## Firewall (UFW)

```bash
ufw status                  # show rules
ufw allow 80/tcp            # open HTTP
ufw allow 443/tcp           # open HTTPS
ufw deny 8080               # block a port
ufw reload
```

---

## Disk, Memory, Processes

```bash
# Disk usage
df -h                       # filesystem overview
du -sh /opt/pattern         # size of project directory
du -sh /opt/pattern/*       # size of each subfolder

# Memory
free -h

# CPU / process overview
top                         # live (press q to quit)
htop                        # nicer live view (if installed)

# Find what's using a port
lsof -i :8000
ss -tlnp | grep 8000

# Kill a process by PID
kill <PID>
kill -9 <PID>               # force kill
```

---

## Files & Navigation

```bash
# Navigate
cd /opt/pattern
ls -la                      # list all files with details
ls -lah                     # same, with human-readable sizes

# Search for files by name
find /opt/pattern -name "*.py" | head -20

# Search file contents
grep -r "search_term" /opt/pattern --include="*.py"
grep -rn "search_term" .    # -n shows line numbers

# Tail a file (last 50 lines)
tail -50 /opt/pattern/logs/pattern.log

# Follow a file live
tail -f /opt/pattern/logs/pattern.log

# Edit a file
nano /opt/pattern/.env
```

---

## SSL / Certbot

```bash
# Get or renew certificate
certbot --nginx -d yourdomain.com

# Check certificate status
certbot certificates

# Test auto-renewal
certbot renew --dry-run
```

---

## Docker (if used)

```bash
docker ps                   # running containers
docker ps -a                # all containers
docker logs <container>     # container logs
docker logs -f <container>  # follow logs
docker restart <container>
docker stop <container>
docker start <container>
```

---

## Common Workflows

### Deploy new code from GitHub

```bash
cd /opt/pattern
git pull origin main
source venv/bin/activate
pip install -r requirements.txt    # if deps changed
systemctl restart pattern
journalctl -u pattern -f           # watch it come up
```

### Quick health check

```bash
systemctl status pattern
systemctl status postgresql
systemctl status redis-server
systemctl status nginx
df -h
free -h
```

### Debug a crash

```bash
journalctl -u pattern -n 200 --no-pager
# or run manually to see full traceback:
cd /opt/pattern
source venv/bin/activate
python main.py
```

### Edit environment variables

```bash
nano /opt/pattern/.env
systemctl restart pattern          # pick up changes
```
