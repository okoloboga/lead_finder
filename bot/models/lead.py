import datetime
from sqlalchemy import (
    Integer,
    String,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, Mapped, relationship
from .base import Base

class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (
        UniqueConstraint("program_id", "telegram_username", name="uq_lead_program_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey('programs.id', ondelete='SET NULL'), nullable=True)

    # Core contact info
    telegram_username: Mapped[str] = mapped_column(String(100), nullable=False)

    # Outreach status: new / contacted / skipped
    status: Mapped[str] = mapped_column(String(20), default="new")
    
    # Key qualification results for display
    qualification_score: Mapped[int] = mapped_column(Integer, nullable=False)
    business_summary: Mapped[str] = mapped_column(Text, nullable=True)
    pains_summary: Mapped[str] = mapped_column(Text, nullable=True)
    interest_summary: Mapped[str] = mapped_column(Text, nullable=True)
    solution_idea: Mapped[str] = mapped_column(Text, nullable=True)
    recommended_message: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Raw data for full context
    raw_qualification_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    raw_user_profile_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    raw_llm_input: Mapped[str] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    program: Mapped["Program"] = relationship("Program")

    def __repr__(self) -> str:
        return f"<Lead(id={self.id}, username='{self.telegram_username}', score={self.qualification_score})>"
