"""Request / response models of the resolution API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.resolution.types import Policy, Resolution, Step, TraceEntry


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., min_length=1, max_length=64)
    filter: str | None = Field(None, max_length=64)
    on_unusable: Literal["fail", "skip"] = "fail"

    def to_step(self) -> Step:
        return Step(role=self.role, filter=self.filter, on_unusable=self.on_unusable)


class PolicyPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[StepIn] = Field(..., min_length=0, max_length=20)
    use_organization_default: bool = True
    notes: str | None = Field(None, max_length=1000)


class ExpansionOut(BaseModel):
    role: str
    from_role: str
    expander: str


class PolicyOut(BaseModel):
    facet: str
    subject: str
    layer: str
    description: str
    roles: list[str]
    expansions: list[ExpansionOut]
    steps: list[dict[str, Any]]
    use_organization_default: bool

    @classmethod
    def of(cls, policy: Policy) -> PolicyOut:
        return cls(
            facet=policy.facet, subject=policy.subject, layer=policy.layer, description=policy.description,
            roles=sorted(policy.roles),
            expansions=[ExpansionOut(role=e.role, from_role=e.from_role, expander=e.expander)
                        for e in policy.expansions],
            steps=[s.as_dict() for s in policy.steps], use_organization_default=policy.use_organization_default,
        )


class FacetOut(BaseModel):
    code: str
    description: str
    filters: list[str]
    context_schema: dict[str, Any]
    policies: list[PolicyOut]


class OwnerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., min_length=1, max_length=64, description="core.entity_types code")
    id: int = Field(..., gt=0)


class SubjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: dict[str, OwnerIn | list[OwnerIn] | None] = Field(default_factory=dict)
    organization_id: int | None = Field(None, description="Defaults to the request's organization")
    context: dict[str, Any] = Field(default_factory=dict)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjects: list[SubjectIn] = Field(..., min_length=1, max_length=1000)
    explain: bool = False


class TraceOut(BaseModel):
    step: int | None
    role: str
    owner: str | None
    result: str
    detail: str | None = None

    @classmethod
    def of(cls, entry: TraceEntry) -> TraceOut:
        return cls(step=entry.step, role=entry.role, owner=str(entry.owner) if entry.owner else None,
                   result=entry.result, detail=entry.detail)


class ResolutionOut(BaseModel):
    outcome: str
    via: str | None
    owner: str | None
    reason: str | None
    values: list[dict[str, Any]]
    trace: list[TraceOut]

    @classmethod
    def of(cls, result: Resolution, values: list[dict[str, Any]]) -> ResolutionOut:
        return cls(outcome=result.outcome.value, via=result.via, owner=str(result.owner) if result.owner else None,
                   reason=result.reason, values=values, trace=[TraceOut.of(t) for t in result.trace])


__all__ = [
    "FacetOut",
    "OwnerIn",
    "PolicyOut",
    "PolicyPut",
    "ResolutionOut",
    "ResolveRequest",
    "StepIn",
    "SubjectIn",
    "TraceOut",
]
