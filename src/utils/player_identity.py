"""Shared interpretation of saved player localization choices."""
SOURCES = ("name", "medal", "appearance")


def identity_selection(cfg):
    identity = cfg.get("player_identity", {})
    if "sources" in identity:
        sources = identity["sources"]
        policy = identity.get("match_policy", "any")
        return (list(sources) if isinstance(sources, (list, tuple)) else [],
                policy if policy in ("any", "all") else "any")
    if identity.get("enable"):
        sources = ["name"]
        if identity.get("require_medal", False):
            sources.append("medal")
        if identity.get("require_appearance", False):
            sources.append("appearance")
        return sources, "any"
    sources = []
    if cfg.get("title", {}).get("enable", False):
        sources.append("medal")
    if cfg.get("appearance", {}).get("enable", False):
        sources.append("appearance")
    return sources, "any"


def migrate_legacy_identity(cfg):
    """Old launchers can rewrite the file without explicit sources/policy.

    Treat their auxiliary checkboxes as complementary sources; only a saved
    explicit ``all`` policy requests strict simultaneous verification.
    """
    identity = cfg.get("player_identity", {})
    if (not identity.get("enable") or "sources" in identity
            or not (identity.get("require_medal") or identity.get("require_appearance"))):
        return False
    sources, _ = identity_selection(cfg)
    identity.update(sources=sources, match_policy="any")
    return True
