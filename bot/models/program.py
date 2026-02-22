import datetime
from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Boolean,
    Text
)
from sqlalchemy.orm import mapped_column, Mapped, relationship
from .base import Base
import config

class Program(Base):
    __tablename__ = 'programs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    niche_description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Settings
    min_score: Mapped[int] = mapped_column(Integer, default=5)
    max_leads_per_run: Mapped[int] = mapped_column(Integer, default=20)
    enrich: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Schedule
    schedule_time: Mapped[str] = mapped_column(String(5), default="09:00")  # HH:MM format

    # Telegram user ID of the program owner (for scheduler notifications)
    owner_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    
    chats: Mapped[list["ProgramChat"]] = relationship("ProgramChat", back_populates="program", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Program(id={self.id}, name='{self.name}')>"

class ProgramChat(Base):
    __tablename__ = 'program_chats'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey('programs.id', ondelete='CASCADE'), nullable=False)
    chat_username: Mapped[str] = mapped_column(String(100), nullable=False)

    program: Mapped["Program"] = relationship("Program", back_populates="chats")

    def __repr__(self) -> str:
        return f"<ProgramChat(program_id={self.program_id}, chat='{self.chat_username}')>"
