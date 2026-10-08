"""
Schémas Employé. Le frontend Angular (`core/models/employee.model.ts`) attend
du camelCase (firstName, hireDate, …) : on sérialise donc avec des alias
camelCase tout en acceptant les deux formes en entrée (populate_by_name).
"""
from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.employee import CONTRACT_TYPES, GENDERS

_GENDER_PATTERN = "^(" + "|".join(GENDERS) + ")$"
_CONTRACT_PATTERN = "^(" + "|".join(CONTRACT_TYPES) + ")$"


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class EmployeeCreate(_CamelModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    email: str = Field(..., max_length=255)
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    salary: float | None = Field(default=None, ge=0)
    hire_date: datetime | None = None
    status: str = Field(default="active", pattern="^(active|inactive|on-leave)$")
    birth_date: date | None = None
    gender: str | None = Field(default=None, pattern=_GENDER_PATTERN)
    contract_type: str | None = Field(default=None, pattern=_CONTRACT_PATTERN)
    education_level: str | None = Field(default=None, max_length=50)



class EmployeeUpdate(_CamelModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    salary: float | None = Field(default=None, ge=0)
    hire_date: datetime | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive|on-leave)$")
    birth_date: date | None = None
    gender: str | None = Field(default=None, pattern=_GENDER_PATTERN)
    contract_type: str | None = Field(default=None, pattern=_CONTRACT_PATTERN)
    education_level: str | None = Field(default=None, max_length=50)



class EmployeeResponse(_CamelModel):
    id: UUID
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    position: str | None = None
    department: str | None = None
    salary: float | None = None
    hire_date: datetime | None = None
    status: str
    birth_date: date | None = None
    gender: str | None = None
    contract_type: str | None = None
    education_level: str | None = None
    # `age` et `missing_fields` sont des PROPRIÉTÉS du modèle, jamais des
    # colonnes : un âge stocké devient faux au bout d'un an, et une liste de
    # manques stockée se désynchronise dès la première modification.
    age: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
