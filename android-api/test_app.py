import inspect

import pytest
from fastapi import HTTPException

import app


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.sql = ""
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.row


def test_password_hash_round_trip_and_salt():
    first = app.make_password_hash("Neuron-Test-2026")
    second = app.make_password_hash("Neuron-Test-2026")
    assert first != second
    assert app.check_password("Neuron-Test-2026", first)
    assert not app.check_password("wrong-password", first)


@pytest.mark.parametrize(("raw", "expected"), [
    (None, None), ("", None), ("—", None),
    ("1", 1), (2, 2), ("5", 5),
])
def test_journal_score_accepts_valid_values(raw, expected):
    assert app.parse_journal_score(raw) == expected


@pytest.mark.parametrize("raw", ["0", "6", "-1", "3.5", "abc", {}, []])
def test_journal_score_rejects_invalid_values(raw):
    with pytest.raises(HTTPException) as error:
        app.parse_journal_score(raw)
    assert error.value.status_code == 400


def test_teacher_login_id_resolves_through_neuron_account():
    cursor = FakeCursor({"id": 73})
    assert app.teacher_id_for(cursor, -42) == 73
    assert "login_accounts" in cursor.sql
    assert cursor.params == (42,)


def test_legacy_teacher_id_still_resolves_during_transition():
    cursor = FakeCursor({"id": 73})
    assert app.teacher_id_for(cursor, 123456) == 73
    assert "chat_id" in cursor.sql
    assert cursor.params == (123456,)


def test_password_login_has_no_telegram_bot_dependency():
    source = inspect.getsource(app.password_login)
    assert "BOT_TOKEN" not in source
    assert "verified_user" not in source
    assert "telegram.org" not in source.lower()
