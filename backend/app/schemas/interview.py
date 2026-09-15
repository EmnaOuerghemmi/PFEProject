"""
Pydantic schemas for interview invitations & slots.
"""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# ─── REQUESTS ────────────────────────────────────────────────────

class ScheduleInterviewRequestV2(BaseModel):
    """Body for POST /applications/{app_id}/schedule-interview (RH side)."""
    slots: list[datetime] = Field(
        ..., min_length=1, max_length=5,
        description="ISO datetime list. The candidate will pick exactly one.",
    )
    duration_minutes: int = Field(default=30, ge=10, le=240,
                                  description="Slot duration. Defaults to 30 min.")
    message: str = Field(default="", max_length=2000,
                         description="Optional custom note shown in the email + UI.")
    expires_in_hours: int = Field(default=48, ge=1, le=336,
                                  description="Link lifetime. Default 48h.")


class ConfirmSlotRequest(BaseModel):
    """Body for POST /interview/confirm/{token} (public candidate side)."""
    slot_id: UUID


class CancelInvitationRequest(BaseModel):
    """Body for POST /interview/invitations/{id}/cancel (RH side)."""
    reason: str = Field(default="", max_length=1000)


# ─── RESPONSES ───────────────────────────────────────────────────

class InterviewSlotResponse(BaseModel):
    id: UUID
    invitation_id: UUID
    start_at: datetime
    end_at: datetime
    is_selected: bool

    model_config = {"from_attributes": True}


class InvitationResponse(BaseModel):
    """Internal RH-side response with everything."""
    id: UUID
    application_id: UUID
    token: str
    status: str
    message: str | None = None
    expires_at: datetime
    confirmed_slot_id: UUID | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    slots: list[InterviewSlotResponse]
    # candidate / job context (denormalised for the RH UI)
    candidate_name: str | None = None
    candidate_email: str | None = None
    job_title: str | None = None
    public_url: str
    # Lien de visioconférence de l'entretien confirmé (Meet ou Jitsi).
    meet_url: str | None = None

    model_config = {"from_attributes": True}


class PublicInvitationView(BaseModel):
    """
    Safe view shown on the public confirmation page (NO token leakage, no
    candidate email, just enough context to confirm).
    """
    status: str
    expires_at: datetime
    message: str | None = None
    candidate_name: str
    job_title: str
    job_description: str | None = None
    company_name: str = "PIQBIT"
    slots: list[InterviewSlotResponse]
    confirmed_slot: InterviewSlotResponse | None = None
    # Renseigné une fois le créneau confirmé et le lien généré.
    meet_url: str | None = None


# ─── RH CALENDAR (aggregated view across all invitations) ────────

class CalendarSlot(BaseModel):
    """A single slot displayed in the RH "calendar" page with computed state."""
    id: UUID
    invitation_id: UUID
    application_id: UUID
    start_at: datetime
    end_at: datetime
    state: str  # "AVAILABLE" | "PROPOSED" | "RESERVED"
    candidate_name: str | None = None
    job_title: str | None = None
    invitation_status: str
    confirmed_at: datetime | None = None
    meet_url: str | None = None


class CalendarResponse(BaseModel):
    total: int
    items: list[CalendarSlot]
