# Media + GarageFS — production rollout runbook

For the prod VM (`dlp-prod`, `e2-standard-8`, deploy dir
`~/th-middleware/apps/core-platform/deployment`, `.env` copied from
`.env.prod.example`, bare `docker compose` = base + prod override). Design and
behaviour: [`media-storage.md`](./media-storage.md).

**Shape of the change.** The prod image is *baked* (no source bind mount like dev),
so this needs a rebuild. The migration is additive except for dropping the unused
`public.media` table, so **old and new code can both run against the new schema** —
that is what makes the order below safe. Expect one short API blip when the backend
container is recreated (single instance); do it off-peak.

Do the steps **in order**. Steps 3 and 9 are the two that can hurt if reordered.

---

## 0. Before you touch the VM (on your machine)

1. **Commit everything the chain needs.** The media migration `768753121795` is
   chained after `c7a1e9b2d4f8` (categories) and `cf0e1d2c3b4a` (custom fields). If any
   of those files is untracked, prod's `alembic` fails with *"Can't locate revision"*.
   ```bash
   git status --short        # every new file must be in the commit:
   #   app/modules/media/*  app/tasks/media.py  alembic/versions/*  scripts/garage-*.sh
   #   tests/media_*  tests/test_media_*  docs/media-*.md  (and the categories/custom-fields files)
   ```
   (Past incident: an unanchored `.gitignore` rule silently dropped `app/modules/media/`
   from a commit. It is anchored now — still check.)
2. Test suite green; push.
3. **DNS (optional, for the Garage Web UI only):** `garage.dlp.tarrinahealth.com` → the
   VM's public IP. Without it Traefik just logs failed ACME attempts for that host;
   nothing else is affected. Public media itself needs **no** DNS or certificate change
   (same host as the app).

## 1. Preflight on the VM (read-only)

```bash
cd ~/th-middleware/apps/core-platform/deployment
docker compose ps                       # everything healthy before you start
df -h /var/lib/docker; free -m          # Garage adds ~640 MB of memory limits, little disk
docker compose exec backend alembic current
docker compose exec backend alembic heads   # (still the OLD image: shows today's head)
```
The migration refuses to run while the legacy table holds live rows:
```bash
./manage.sh shell-postgres   # then:
SELECT count(*) FILTER (WHERE deleted_at IS NULL) AS live, count(*) AS total FROM public.media;
```
`live` must be `0` (it was `0` in dev; nothing consumed that table). If it is not,
export those rows, then `UPDATE public.media SET deleted_at = now()`.

## 2. Back up

```bash
./manage.sh db-backup
scripts/sync-backups-gcs.sh gs://dlp-prod-backups     # get a copy off the VM
gcloud compute disks snapshot <boot-disk> --zone asia-south1-a --snapshot-names pre-media-$(date +%F)
```
The dump includes `zoho_oauth_credentials` — the only copy of the Zoho refresh token
when `ZOHO_REFRESH_TOKEN` is empty. Do not skip this.

## 3. Add the Garage secrets to `.env` **before** pulling code  ⚠️

`docker-compose.prod.yml` now refuses to render without real Garage secrets. After
the `git pull`, *every* `docker compose …` command (even `ps`) fails until they exist.
```bash
cp .env ".env.bak-$(date +%F)"
cat >> .env <<EOF

# --- Media storage / Garage (docs/media-storage.md) ---
MEDIA_STORAGE_DRIVER=local          # flipped to garage in step 9, not now
GARAGE_RPC_SECRET=$(openssl rand -hex 32)
GARAGE_ADMIN_TOKEN=$(openssl rand -hex 32)
GARAGE_METRICS_TOKEN=$(openssl rand -hex 32)
GARAGE_DEFAULT_ACCESS_KEY=GK$(openssl rand -hex 12)
GARAGE_DEFAULT_SECRET_KEY=$(openssl rand -hex 32)
EOF
chmod 600 .env && ./manage.sh env-check
```
**Store these five values in your password manager.** Garage creates its key from them
once, on first boot; changing them later does not re-key an existing Garage (and
changing `GARAGE_RPC_SECRET` breaks its cluster RPC). Optional: `MEDIA_PUBLIC_BASE_URL`
(default `https://dlp.tarrinahealth.com`), `MEDIA_PUBLIC_HOST` (serve `/public/m` from its
own host — needs a DNS A record, and Let's Encrypt issues that host its own certificate).

## 4. Deploy the code and build once

```bash
git pull
docker compose config >/dev/null && echo "compose renders"
docker compose build backend            # one build; celery-*/flower/search-indexer share the tag
docker compose run --rm --no-deps backend python -c "import aioboto3; print('deps ok')"
```

## 5. Migrate — with the new image, old containers still serving

```bash
docker compose run --rm --no-deps backend alembic history -i -r current:head   # review what will run
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend alembic current                      # → 768753121795 (head)
```
Applies (as far as prod is behind): custom fields → categories → **media**
(`media.items` created, `public.media` dropped). Each migration is one transaction: a
failure rolls that migration back and leaves the DB where it was. If it fails,
fix forward or restore the step-2 backup; the old containers are still running untouched.

## 6. Roll the containers

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=40 backend celery-worker | grep -iE "startup_complete|error|traceback"
curl -sf https://dlp.tarrinahealth.com/api/health
```
This recreates backend / celery-worker / celery-beat / flower / search-indexer on the
new image and **creates** `garage` (+ `garage-webui`). The driver is still `local`, so
the app does not need Garage yet and behaves exactly as before.

## 7. Bootstrap Garage

```bash
./manage.sh garage-init         # creates both buckets, grants the key, denies bucket creation. Idempotent.
```
Optional check: `https://garage.dlp.tarrinahealth.com` (user `admin`, the dashboard
password) → two buckets, one key with read+write on both.

## 8. Smoke test on the *local* driver (safe, reversible)

```bash
TOKEN=$(curl -s https://dlp.tarrinahealth.com/api/auth/login -H 'content-type: application/json' \
        -d '{"identifier":"<email, username or phone>","password":"<pw>"}' | jq -r .data.access_token)
curl -s -X POST https://dlp.tarrinahealth.com/api/me/avatar -H "Authorization: Bearer $TOKEN" \
     -F 'file=@some.jpg;type=image/jpeg' | jq
# poll until no null remains (a second or two):
curl -s https://dlp.tarrinahealth.com/api/me/profile -H "Authorization: Bearer $TOKEN" | jq .data.avatar_urls
curl -sI https://dlp.tarrinahealth.com/public/m/<media_id>/medium        # 200, image/webp, immutable — no credentials
curl -s -X DELETE https://dlp.tarrinahealth.com/api/me/avatar -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}\n'   # 204
```

## 9. Flip to Garage  ⚠️ only after step 7

With `MEDIA_STORAGE_DRIVER=garage` the backend does a `HeadBucket` on both buckets at
startup and **refuses to boot** if either is missing — and `restart: always` would
loop it. That is why `garage-init` comes first.
```bash
sed -i 's/^MEDIA_STORAGE_DRIVER=.*/MEDIA_STORAGE_DRIVER=garage/' .env
docker compose up -d backend celery-worker          # recreate only what reads the setting
docker compose logs --tail=30 backend | grep -iE "startup_complete|StorageConfigError"
```
Repeat the step-8 upload; then confirm it landed in Garage and the DB agrees:
```bash
./manage.sh shell-postgres   # SELECT disk, visibility, status, count(*) FROM media.items GROUP BY 1,2,3;
```
Rows uploaded on `local` earlier keep `disk='local'` and keep working (per-row disk).

## 10. Backups for Garage (do not skip — one node = no redundancy)

Nothing else backs up Garage's volumes. Add to the VM's crontab (next to the DB backup sync):
```cron
45 21 * * *  cd ~/th-middleware/apps/core-platform/deployment && ./manage.sh garage-backup && scripts/sync-backups-gcs.sh gs://dlp-prod-backups
```
`garage-backup` mirrors both buckets into `backups/garage/` (one-way; refuses to sync
an empty bucket over a non-empty mirror). Also keep a scheduled GCE disk-snapshot policy
on the VM.

**Restore into a fresh Garage:** `./manage.sh garage-init`, then per bucket
```bash
docker run --rm --network deployment_app-backend -v "$PWD/backups/garage:/backup" \
  -e RCLONE_CONFIG_G_TYPE=s3 -e RCLONE_CONFIG_G_PROVIDER=Other -e RCLONE_CONFIG_G_ENDPOINT=http://garage:3900 \
  -e RCLONE_CONFIG_G_REGION=garage -e RCLONE_CONFIG_G_ACCESS_KEY_ID=<GARAGE_DEFAULT_ACCESS_KEY> \
  -e RCLONE_CONFIG_G_SECRET_ACCESS_KEY=<GARAGE_DEFAULT_SECRET_KEY> \
  rclone/rclone:1.68.2 copy /backup/core-platform-media-public G:core-platform-media-public
```
(Network name = `<compose project>_app-backend`; `docker network ls` if yours differs.)

## 11. Verify over the next 48 h

* `docker compose logs celery-worker | grep -E "media_gc_complete|media_requeued|media_gave_up"` —
  GC purges soft-deleted media after 24 h; the sweeper should be silent.
* Flower: `app.tasks.media.*` succeeding; `gen_variant` failures are recorded per row
  (`SELECT uuid, conversions FROM media.items WHERE status = 'partial_failure'`).
* `docker stats garage` and `du -sh` of the `app_garage_data` volume.

## Rollback

| Situation | Action |
|---|---|
| Garage misbehaves after the flip | `MEDIA_STORAGE_DRIVER=local` in `.env`, `docker compose up -d backend celery-worker`. New uploads go to local disk. **Keep Garage running**: rows already on Garage keep resolving through it. |
| New code misbehaves | `git checkout <previous tag>`, `docker compose up -d --build`. The old code never reads `media.items`, so it runs fine on the migrated schema. |
| Migration failed | It rolled itself back. Fix forward, or restore the step-2 dump. |
| Undo the media migration (only before real use) | `alembic downgrade c7a1e9b2d4f8` — recreates the empty legacy table and drops `media.items`. **Lossy**: rows in `media.items` are gone (bytes stay in Garage, orphaned). |

## Things worth knowing

* **Cross-origin `fetch()`**: `<img src>` from other apps needs nothing. A page that
  `fetch()`es the image bytes is subject to the app-wide `CORS_ORIGINS` allow-list.
* **Different host / CDN later**: set `MEDIA_PUBLIC_HOST` + `MEDIA_PUBLIC_BASE_URL`, or put
  a CDN in front — responses already carry `immutable` cache headers and an `ETag`.
  URLs already handed out on the old host keep working as long as that host does.
* **Web UI exposure**: `garage-webui` holds the Garage admin token and sits behind the same
  basic-auth as Flower/Traefik. If you would rather not expose it, drop the
  `garage-webui` block from `docker-compose.prod.yml` and use `docker exec garage /garage …`.
* The single Garage node is the same single point of failure as local disk. It gives you
  S3 semantics and a clean path to a multi-node cluster later, not resilience today.
