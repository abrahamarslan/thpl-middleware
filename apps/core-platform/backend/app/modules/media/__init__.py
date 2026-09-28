"""Media module — images with generated conversions, on local disk or GarageFS.

* ``storage`` / ``storage_sync``  async (API) and sync (Celery) providers; every
  row records its own ``disk``, so switching MEDIA_STORAGE_DRIVER never strands
  an issued URL.
* ``conversions``  declarative per-collection variants (thumb / medium / large).
* ``imaging``      Pillow: validation, EXIF/GPS strip, variant rendering.
* ``service``      upload/replace/delete orchestration (API path).
* ``public_api``   the deliberately unauthenticated ``/public/m/{id}/{variant}``.

Pipeline: app/tasks/media.py. Design and ops notes: docs/media-storage.md.
"""
