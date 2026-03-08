#!/bin/bash
# Pattern Project - Daily Google Drive Backup (cron script)
#
# Setup:
#   1. Copy to server:  scp deploy/backup_cron.sh root@your-server:/opt/pattern/deploy/
#   2. Make executable:  chmod +x /opt/pattern/deploy/backup_cron.sh
#   3. Ensure logs dir:  mkdir -p /opt/pattern/logs
#   4. Add cron entry:   sudo crontab -u pattern -e
#      Add this line for daily backup at 3:00 AM:
#        0 3 * * * /opt/pattern/deploy/backup_cron.sh >> /opt/pattern/logs/backup_cron.log 2>&1
#
#   To verify the cron entry:
#      sudo crontab -u pattern -l

set -euo pipefail

PATTERN_DIR="/opt/pattern"
VENV_PYTHON="${PATTERN_DIR}/venv/bin/python"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# Load environment variables (needed for config)
if [ -f "${PATTERN_DIR}/.env" ]; then
    set -a
    source "${PATTERN_DIR}/.env"
    set +a
fi

cd "${PATTERN_DIR}"

echo "${LOG_PREFIX} Starting scheduled backup..."

${VENV_PYTHON} -c "
from communication.drive_backup_gateway import init_drive_backup_gateway, run_drive_backup
init_drive_backup_gateway()
result = run_drive_backup()
print(result)
if not result.success:
    raise SystemExit(1)
"

EXIT_CODE=$?

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "${LOG_PREFIX} Backup completed successfully."
else
    echo "${LOG_PREFIX} ERROR: Backup failed with exit code ${EXIT_CODE}."
fi

exit ${EXIT_CODE}
