from urllib.parse import urljoin, urlparse, parse_qsl, urlencode

def _normalize_url(url: str) -> str:
    """
    Strips fragment/hash components and standard tracking parameters from a URL.
    """
    try:
        parsed = urlparse(url)
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_params = []
        for k, v in query_params:
            kl = k.lower()
            if kl.startswith("utm_") or kl in {"fbclid", "gclid", "ref", "amp"}:
                continue
            filtered_params.append((k, v))
        new_query = urlencode(filtered_params) if filtered_params else ""
        return parsed._replace(fragment="", query=new_query).geturl()
    except Exception:
        return url


def clean_and_resolve_url(base_url: str, link_url: str) -> str | None:
    """
    Cleans and resolves a hyperlink URL relative to a base URL.
    Only allows http/https schemes, removes fragments/anchors, and skips self-links.
    """
    try:
        link_stripped = link_url.strip()
        if link_stripped.startswith("#") or not link_stripped:
            return None
            
        resolved = urljoin(base_url, link_stripped)
        parsed = urlparse(resolved)
        if parsed.scheme in ("http", "https"):
            cleaned = _normalize_url(resolved)
            
            # Skip self-links
            base_cleaned = _normalize_url(base_url)
            if cleaned == base_cleaned:
                return None
                
            return cleaned
    except Exception:
        pass
    return None
