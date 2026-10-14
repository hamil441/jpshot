"""Minimal AnkiConnect client (https://foosoft.net/projects/anki-connect/, add-on code 2055492159)."""
from __future__ import annotations

import logging

log = logging.getLogger("jpshot.anki")

NOT_RUNNING = ("Can't reach Anki. Open Anki and make sure the AnkiConnect add-on is installed "
               "(Tools → Add-ons → Get Add-ons… → code 2055492159), then restart Anki.")


class AnkiError(RuntimeError):
    pass


def invoke(url: str, action: str, **params):
    import requests

    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    log.debug("AnkiConnect %s %s", action, {k: (v if k != "note" else "…") for k, v in params.items()})
    try:
        r = requests.post(url, json=payload, timeout=15)
    except requests.exceptions.ConnectionError as e:
        raise AnkiError(NOT_RUNNING) from e
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise AnkiError(str(data["error"]))
    return data.get("result")


def load_collection_info(url: str) -> dict:
    """Decks and note types with their field names (one call each)."""
    decks = sorted(invoke(url, "deckNames"))
    models = sorted(invoke(url, "modelNames"))
    fields = {m: invoke(url, "modelFieldNames", modelName=m) for m in models}
    log.info("Anki: %d decks, %d note types", len(decks), len(models))
    return {"decks": decks, "models": models, "fields": fields}


def add_note(url: str, note: dict) -> int:
    nid = invoke(url, "addNote", note=note)
    log.info("Anki note added: %s", nid)
    return nid


def browse(url: str, note_id: int) -> None:
    invoke(url, "guiBrowse", query=f"nid:{note_id}")
