import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database as db


def test_internal_messages_restore_for_agent_but_not_display(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setattr(db, "_DB_DIR", str(tmp_path))
    monkeypatch.setattr(db, "_local", threading.local())
    db.init_db()
    session_id = db.create_session("visibility")

    db.save_message(session_id, "user", "visible user message")
    db.save_message(
        session_id,
        "user",
        "full skill instructions",
        visibility="internal",
    )

    restored = db.get_session_messages(session_id)
    displayed = db.get_session_display_messages(session_id)

    assert [message["content"] for message in restored] == [
        "visible user message",
        "full skill instructions",
    ]
    assert [message["content"] for message in displayed] == ["visible user message"]
