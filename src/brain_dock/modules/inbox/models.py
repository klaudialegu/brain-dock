"""The inbox's own tables (harness PR 5a). Emails keep no body: only a keyed hash of the
Message-ID, a status and a count. Roles keep the fields the rules and the triage page need,
with the link already stripped of tracking parameters."""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class InboxEmail(SQLModel, table=True):
    __tablename__ = "inbox_email"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True)  # keyed hash of the Message-ID; never the id itself
    received_at: datetime
    status: str  # parsed | needs_review
    reason: str | None = None  # a short code, e.g. no_roles_found
    role_count: int = 0


class InboxRole(SQLModel, table=True):
    """One role, however many emails mentioned it. The four *_key columns are its identity
    (docs/design/pr5-inbox-plan.md, "The role dedupe key"); a missing field is ""."""

    __tablename__ = "inbox_role"
    __table_args__ = (
        UniqueConstraint(
            "company_key", "title_key", "location_key", "link_key", name="uq_inbox_role_identity"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    item_key: str = Field(unique=True)  # the core work item's key (a keyed hash)
    company: str
    title: str
    location: str
    company_key: str
    title_key: str
    location_key: str
    link_key: str  # the normalized link, also what the page shows
    location_kind: str | None = None  # remote | hybrid | onsite; None: missing
    location_city: str | None = None  # normalized
    seniority: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None  # the top of the range; the rules compare this
    salary_currency: str | None = None
    salary_period: str | None = None  # year | month | hour
    status: str = "new"  # new -> suggested | skipped | needs_review; suggested -> accepted
    reason: str | None = None  # the rule's reason code, kept for the rejection log
    created_at: datetime


class InboxRoleSource(SQLModel, table=True):
    """Which emails mentioned a role: the same role in two alerts is one row, two sources."""

    __tablename__ = "inbox_role_source"

    role_id: int = Field(foreign_key="inbox_role.id", primary_key=True)
    email_id: int = Field(foreign_key="inbox_email.id", primary_key=True)
