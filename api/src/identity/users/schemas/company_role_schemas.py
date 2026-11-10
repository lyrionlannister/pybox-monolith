"""Schemas de request/response para roles de empresa."""

import uuid

from pydantic import Field

from core.base.schema_base import BaseSchema


class CompanyRoleCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permission_names: list[str] = Field(default_factory=list)


class CompanyRoleUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    permission_names: list[str] | None = None


class CompanyRoleResponse(BaseSchema):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    permission_names: list[str]


class CompanyRoleAssignmentResponse(BaseSchema):
    user_id: uuid.UUID
    company_role_id: uuid.UUID
