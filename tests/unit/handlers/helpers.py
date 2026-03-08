"""Reusable async fakes for handler tests."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class FakeUser:
    id: int
    username: str | None = "tester"
    language_code: str | None = "ru"


class FakeState:
    def __init__(self) -> None:
        self.state = None
        self.data: dict = {}
        self.cleared = False

    async def set_state(self, state) -> None:  # noqa: ANN001
        self.state = state

    async def update_data(self, **kwargs) -> None:  # noqa: ANN003
        self.data.update(kwargs)

    async def get_data(self) -> dict:
        return dict(self.data)

    async def clear(self) -> None:
        self.state = None
        self.data = {}
        self.cleared = True


class FakeMessage:
    def __init__(self, from_user: FakeUser, text: str | None = None) -> None:
        self.from_user = from_user
        self.text = text
        self.answers: list[tuple[str, dict]] = []
        self.edits: list[tuple[str, dict]] = []
        self.reply_markup_edits: list[dict] = []
        self.deleted = False
        self.invoice_calls: list[dict] = []
        self.successful_payment = None

    async def answer(self, text: str, **kwargs):  # noqa: ANN003
        self.answers.append((text, kwargs))

    async def edit_text(self, text: str, **kwargs):  # noqa: ANN003
        self.edits.append((text, kwargs))

    async def edit_reply_markup(self, **kwargs):  # noqa: ANN003
        self.reply_markup_edits.append(kwargs)

    async def delete(self):
        self.deleted = True

    async def answer_invoice(self, **kwargs):  # noqa: ANN003
        self.invoice_calls.append(kwargs)


class FakeCallback:
    def __init__(self, from_user: FakeUser, data: str = "", message=None):  # noqa: ANN001
        self.from_user = from_user
        self.data = data
        self.message = message or FakeMessage(from_user)
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False):
        self.answers.append((text, show_alert))


class FakeSession:
    def __init__(self, users: dict[int, object] | None = None):
        self.users = users or {}
        self.commits = 0
        self.added: list[object] = []

    async def get(self, model, key):  # noqa: ANN001
        return self.users.get(key)

    async def commit(self):
        self.commits += 1

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)

    async def execute(self, query):  # noqa: ANN001
        # minimal execute for start._touch_user(): return first matching user by id
        target = None
        for criterion in getattr(query, "_where_criteria", []):
            right = getattr(criterion, "right", None)
            target = getattr(right, "value", None)
        user = self.users.get(target)
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(first=lambda: user)
        )
