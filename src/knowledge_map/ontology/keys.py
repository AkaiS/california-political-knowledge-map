"""Node primary key minting, as an ontology-level contract.

Every ingester mints node ids by importing from here rather than formatting
its own.  Two ingesters that mint the same key for one entity enrich a single
node; two that disagree write duplicates nothing downstream can tell apart.
"""

import re
import unicodedata

#: Stands in for the session segment of a :func:`bill_key` when none could be
#: resolved.  Stable across re-ingestion, but provisional: the authoritative
#: session re-keys the node.
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

    ``AB 1`` recurs every session, so the session qualifies the key.  Pass
    ``designation`` where one could be recovered; ``surface`` is the article's
    own string, keyed on when it could not, so an unidentified Bill still keeps
    a stable key across re-ingestions.
    """

    return f"Bill:{session or UNRESOLVED_SESSION}:{slug(designation or surface)}"
