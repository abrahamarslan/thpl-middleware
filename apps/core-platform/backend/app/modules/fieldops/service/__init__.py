"""Field-ops business rules. Routes call these; nothing here authorizes (the HTTP edge does,
``rbac.deps.Perm``) — a service called by a task is trusted code (docs/rbac-module.md §4.9)."""
