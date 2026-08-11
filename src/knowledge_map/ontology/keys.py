"""Node primary key minting, as an ontology-level contract.

A node's ``id`` is the only thing two ingesters have to agree on byte-for-byte.
When a later legislative ingester meets a ``Bill`` the news pipeline already
wrote, minting the same key *enriches* that node; minting a different one puts a
second ``Bill`` beside it. Nothing downstream can tell the two apart afterwards.

So the minting rule lives here as a lookup rather than as an expression inlined
at each write site: an ingester gets the key right by importing it, without
having to read the news write path and reproduce its string formatting.
"""

import re
import unicodedata

#: Stands in for the session segment of a :func:`bill_key` when no session could
#: be resolved or inferred. The key is still stable — re-ingesting the same
#: unresolved bill lands on the same node — but it is provisional, and the
#: authoritative session re-keys it.
UNRESOLVED_SESSION = "unresolved"


def slug(value: str) -> str:
    """Fold a name to the ASCII-lowercase-hyphen form keys are built from."""

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def derived_key(label: str, name: str) -> str:
    """Mint the general node key: the label and the slugged name.

    This is the key for every label whose identity is carried by its name alone.
    ``Bill`` is the exception — see :func:`bill_key`.
    """

    return f"{label}:{slug(name)}"


def bill_key(session: str | None, number: str | None, name: str) -> str:
    """Mint a ``Bill`` key, which is qualified by legislative session.

    A bill number identifies a bill only within a session — ``AB 1`` recurs every
    session by design — so the number alone would conflate unrelated bills.
    ``number`` is the normalized bill number where one could be recovered;
    ``name`` is the extracted surface form, used when it could not.
    """

    return f"Bill:{session or UNRESOLVED_SESSION}:{slug(number or name)}"
