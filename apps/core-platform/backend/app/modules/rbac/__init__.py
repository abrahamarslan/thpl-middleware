"""RBAC — permission catalogue, role permission sets, contextual grants and the evaluator.

    catalogue.py   the audited list of every permission (code-owned)
    templates.py   system role templates seeded per organization
    model.py       rbac.permissions · rbac.role_permissions · rbac.user_roles
    engine.py      grant loading (base role + assignments + team roles), scope matching, cache
    deps.py        FastAPI guards: Perm(code, target=…), GrantsDep, Target
    service.py     assign/revoke, role permission edits, guardrails
    context.py     evaluating permissions OUTSIDE an HTTP request (Celery, consumers)

See docs/rbac-module.md. Import the pieces you need from the submodules — this package
does not re-export, so importing ``rbac.catalogue`` never pulls in the ORM.
"""
