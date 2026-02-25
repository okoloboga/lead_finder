import datetime
from sqlalchemy import (
    BigInteger,
    Integer,
    Float,
    String,
    DateTime,
    ForeignKey,
    Boolean,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, Mapped, relationship
from .base import Base


class PainCluster(Base):
    """Cluster of similar pains grouped by topic."""

    __tablename__ = "pain_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    pain_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_intensity: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=True
    )
    last_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=True
    )
    trend: Mapped[str] = mapped_column(
        String(20), default="stable"
    )
    post_generated: Mapped[bool] = mapped_column(
        Boolean, default=False
    )

    program: Mapped["Program"] = relationship("Program")  # noqa: F821
    pains: Mapped[list["Pain"]] = relationship(
        "Pain", back_populates="cluster"
    )
    posts: Mapped[list["GeneratedPost"]] = relationship(
        "GeneratedPost", back_populates="cluster"
    )

    def __repr__(self) -> str:
        return (
            f"<PainCluster(id={self.id}, name='{self.name}', "
            f"count={self.pain_count})>"
        )


class Pain(Base):
    """Individual pain extracted from a chat message."""

    __tablename__ = "pains"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id", "source_chat", "original_quote",
            name="uq_pain_message_quote",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    original_quote: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    intensity: Mapped[str] = mapped_column(String(10), nullable=False)
    business_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    source_chat: Mapped[str] = mapped_column(String(100), nullable=False)
    source_message_id: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    source_message_link: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    source_user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    source_username: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    message_date: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=True
    )
    collected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("pain_clusters.id", ondelete="SET NULL"), nullable=True
    )
    used_in_post: Mapped[bool] = mapped_column(Boolean, default=False)

    cluster: Mapped["PainCluster | None"] = relationship(
        "PainCluster", back_populates="pains"
    )
    program: Mapped["Program"] = relationship("Program")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Pain(id={self.id}, category='{self.category}', "
            f"intensity='{self.intensity}')>"
        )


class GeneratedPost(Base):
    """Draft post generated from a pain cluster."""

    __tablename__ = "generated_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("pain_clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    post_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    cluster: Mapped["PainCluster"] = relationship(
        "PainCluster", back_populates="posts"
    )

    def __repr__(self) -> str:
        return (
            f"<GeneratedPost(id={self.id}, type='{self.post_type}', "
            f"status='{self.status}')>"
        )
