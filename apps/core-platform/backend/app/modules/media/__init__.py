"""Media module — Spatie-MediaLibrary-style attachments with conversions.

Any model gains a media gallery by inheriting HasMediaMixin and declaring
its conversions:

    class Shop(IntPKMixin, TimestampMixin, HasMediaMixin, Base):
        __media_conversions__ = {"thumb": (150, 150), "optimized": (800, 800)}

Storage is a strategy (local disk today, S3 tomorrow — swap via
MEDIA_STORAGE_DRIVER without touching call sites); image conversions run in
Celery (documents queue), never in the request path.
"""
