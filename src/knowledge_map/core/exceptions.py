from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError

def classify_exception(e: Exception) -> bool:
    """
    Identifies non-breaking errors that can be routed to the Dead Letter Queue
    rather than aborting the batch process.
    """
    return isinstance(e, (CoreferenceResolutionError, ExtractionError))
