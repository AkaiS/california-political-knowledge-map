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


def bill_key(session: str | None, designation: str | None, surface: str) -> str:
    """Mint a ``Bill`` key, which is qualified by legislative session.

    A Bill Designation identifies a bill only within a session — ``AB 1`` recurs
    every session by design — so the designation alone would conflate unrelated
    bills. ``designation`` is the Bill's name where one could be recovered;
    ``surface`` is the string the article used, keyed on when it could not, so an
    unidentified Bill still keeps a stable key across re-ingestions.
    """

    return f"Bill:{session or UNRESOLVED_SESSION}:{slug(designation or surface)}"
