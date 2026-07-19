from urllib.parse import urlparse
from app.models.entities import RightsStatus


DISPLAY_ALLOWED = {
    RightsStatus.PUBLIC_DOMAIN.value,
    RightsStatus.APPROVED_WITH_ATTRIBUTION.value,
    RightsStatus.FACT_GROUNDING_ALLOWED.value,
    RightsStatus.DERIVATIVE_GENERATION_ALLOWED.value,
}
GENERATION_ALLOWED = {
    RightsStatus.PUBLIC_DOMAIN.value,
    RightsStatus.FACT_GROUNDING_ALLOWED.value,
    RightsStatus.DERIVATIVE_GENERATION_ALLOWED.value,
}


def domain_allowed(url: str, allowlist: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowlist)


def can_fetch_full_text(rights_status: str) -> bool:
    return rights_status in GENERATION_ALLOWED


def can_use_for_generation(rights_status: str, approved: bool) -> bool:
    return approved and rights_status in GENERATION_ALLOWED
