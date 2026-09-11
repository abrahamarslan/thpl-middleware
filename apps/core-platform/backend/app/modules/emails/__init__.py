"""Emails module — reusable transactional email with full lifecycle tracking.

Layers:
  provider.py   provider-neutral OutboundEmail/ProviderResult + registry
                (Resend adapter registered; get_email_provider() patch point)
  templates.py  Jinja2 template registry + templates/ (callers pass a name+ctx)
  service.py    compose-and-queue, send_template_email, webhook processing
  tasks         app/tasks/emails.send_email drives the provider with retries

Flow: compose -> persist (status=pending) -> Celery send -> provider webhooks
build the timeline (sent -> delivered -> opened -> clicked / bounced) in
email_events. Sender provenance (actor/ip/request_id) is captured at compose
time; attachments reuse the documents module (single source of file truth).
"""
