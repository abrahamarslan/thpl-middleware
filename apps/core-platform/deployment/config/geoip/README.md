# GeoIP databases

The request-audit emails/logs show a city/country for the caller's IP when
GeoIP is enabled. MaxMind's GeoLite2 databases are **not committed** (their
licence forbids redistribution), so this directory is empty by default and
`GEOIP_ENABLED=false` makes every lookup a no-op.

## Enable

1. Create a free MaxMind account and download **GeoLite2-City** (or
   GeoLite2-Country): <https://www.maxmind.com/en/geolite2/signup>
2. Drop the extracted `.mmdb` here, e.g.
   `deployment/config/geoip/GeoLite2-City.mmdb`.
3. In `deployment/.env`:

   ```
   GEOIP_ENABLED=true
   GEOIP_CITY_DB_PATH=/app/geoip/GeoLite2-City.mmdb
   GEOIP_COUNTRY_DB_PATH=/app/geoip/GeoLite2-Country.mmdb
   ```

4. Restart the backend. The DB is mounted read-only at `/app/geoip`.

Private/loopback addresses are never looked up. If the file is missing or
unreadable the lookup silently returns no location (GeoIP is enrichment, never
a hard dependency).
