"""Home's layout and the shell's settings (ADR 0016). Tables only, so the database module
can register them without importing anything else; the logic is in layout.py."""

from sqlmodel import Field, SQLModel


class CoreLayout(SQLModel, table=True):
    __tablename__ = "core_layout"

    card_id: str = Field(primary_key=True)
    position: int
    shown: bool
    size: str


class CoreSetting(SQLModel, table=True):
    __tablename__ = "core_setting"

    key: str = Field(primary_key=True)
    value: str
