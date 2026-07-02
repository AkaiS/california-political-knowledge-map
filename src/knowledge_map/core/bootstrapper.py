import logging

logger = logging.getLogger(__name__)

def bootstrap_publication_stub(pub_id: str) -> None:
    """
    Seam for invoking the Publication Bootstrapper.
    The design/implementation of the bootstrapper is deferred to a separate PRD.
    """
    msg = f"Publication Bootstrapper: initialization deferred for publication '{pub_id}'. (See design in separate PRD)"
    logger.info(msg)
    print(msg)
