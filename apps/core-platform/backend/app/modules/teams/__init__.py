"""Teams — departments, job titles, team types/roles, teams and memberships.

    enums.py model.py schema.py crud.py service.py api.py grants.py lang/   the feature
    ../rbac/                                                                the permission engine it plugs into

HTTP: /api/departments, /api/job-titles, /api/team-types, /api/team-roles,
/api/teams (+ members), /api/me/teams. See docs/rbac-module.md.
"""

from app.modules.teams.model import Department, JobTitle, Team, TeamRole, TeamType, UserTeam

__all__ = ["Department", "JobTitle", "Team", "TeamRole", "TeamType", "UserTeam"]
