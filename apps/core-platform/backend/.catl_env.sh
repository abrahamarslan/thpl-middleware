# Scratch environment for the catalogue build (containers catl-scratch-pg :15440, catl-scratch-redis :56395).
# Usage: source .catl_env.sh
export DATABASE_URL=postgresql+asyncpg://app:app_password@localhost:15440/app_db
export REDIS_URL=redis://localhost:56395/0
export CELERY_BROKER_URL=redis://localhost:56395/2
export CELERY_RESULT_BACKEND=redis://localhost:56395/3
cd /home/a2/projects/th-middleware/apps/core-platform/backend
