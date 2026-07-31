"""Emails module — transactional email via Resend with full lifecycle tracking.

Compose -> persist -> Celery send -> provider webhooks build the timeline
(sent -> delivered -> opened -> clicked / bounced) in email_events.
Attachments reuse the documents module (single source of truth for files).
"""
