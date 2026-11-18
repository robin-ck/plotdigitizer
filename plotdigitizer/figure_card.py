"""Stage 3: Figure Card.

For now the Figure Card is written by hand and only loaded and validated here.

TODO (stage 3, LLM step P3): generate the card from caption, referring
paragraphs, methods/results and the figure image; open questions go to the
user. Tick POSITIONS are never taken from the model, only tick values.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "figure_card.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_card(card: dict) -> None:
    import jsonschema
    jsonschema.validate(card, load_schema())
    ids = [p["id"] for p in card["panels"]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate panel ids: {ids}")


def load_card(path: str | Path) -> dict:
    card = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_card(card)
    return card


def generate_card(*args, **kwargs):
    raise NotImplementedError("LLM-generated Figure Cards (stage 3, prompt P3) are not implemented yet")
