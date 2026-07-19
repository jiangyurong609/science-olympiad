from app.services.rights import can_fetch_full_text, can_use_for_generation, domain_allowed


def test_rights_policy_defaults_deny():
    assert not can_fetch_full_text("metadata_only")
    assert not can_use_for_generation("fact_grounding_allowed", False)
    assert can_use_for_generation("fact_grounding_allowed", True)


def test_domain_allowlist():
    assert domain_allowed("https://science.nasa.gov/test", {"nasa.gov"})
    assert not domain_allowed("https://evil-nasa.gov/test", {"nasa.gov"})
