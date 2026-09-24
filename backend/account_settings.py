"""Settings (#151): what the Settings tab and its detail pages show.

Replaced the old Profile and Plates pages. This module only *reads*: it
assembles the list page's one-line values and the detail pages' data from
the modules that own them (training_log for the protocol, progression and
bodyweight; plates for the rack). Writes stay where they always were
(`training_log.save_protocol`, `plates.tap_plate`, `auth.set_display_name`,
...), so the routers remain shallow adapters.
"""

from sqlmodel import Session, select

from backend import plates, training_log
from backend.models import GripType, User

# The "Saved ✓" toast's text, keyed by the `?saved=` value a no-JS form post
# lands back on (and what an htmx autosave answers with). Only these fixed
# strings are ever shown -- never echoed input.
SAVED_MESSAGES = {
    "name": "Saved",
    "training": "Saved",
    "progression": "Saved",
    "override": "Override saved",
    "override-removed": "Override removed",
    "plates": "Saved",
    "sound": "Saved",
    "bodyweight": "Bodyweight logged",
    "restored": "Backup restored",
    "grip-type": "Grip type added",
    "password": "Password reset",
}

# Where each settings form's no-JS path lands (303), by saved key.
PAGES = {
    "name": "/settings/name",
    "training": "/settings/training",
    "progression": "/settings/progression",
    "override": "/settings/progression",
    "override-removed": "/settings/progression",
    "plates": "/settings/plates",
    "sound": "/settings",
    "bodyweight": "/settings",
    "restored": "/settings",
    "grip-type": "/settings/admin",
    "password": "/settings/admin",
}

HAND_ORDER_LABELS = {
    "alternating": "Alternating",
    "sequential": "One hand, then the other",
}

PROGRESSION_LABELS = {
    "weight": "Add weight",
    "set": "Add a set",
    "double": "Reps, then weight",
}


def saved_message(key: str | None) -> str | None:
    return SAVED_MESSAGES.get(key or "")


def _combo_overrides(session: Session, user: User) -> list:
    return [
        ps
        for ps in training_log.list_progression_settings(session, user)
        if ps.grip_type_id is not None and ps.edge_mm is not None
    ]


def settings_view(session: Session, user: User) -> dict:
    """The Settings list page: one short value per row."""
    protocol = training_log.get_protocol(session, user)
    rack = plates.rack_view(session, user)
    owned = sum(p["count"] for p in rack["plates"])
    return {
        "hand_order": HAND_ORDER_LABELS.get(user.hand_order_pref, user.hand_order_pref),
        "protocol": protocol,
        "progression": PROGRESSION_LABELS.get(
            training_log.get_progression_settings(session, user).path, ""
        ),
        "override_count": len(_combo_overrides(session, user)),
        "plate_count": owned,
        "max_load": rack["max_load"],
        "bodyweight": training_log.bodyweight_at(session, user),
    }


def progression_view(session: Session, user: User) -> dict:
    """Settings → Progression: the default path and the per-combo overrides
    (moved from the old Profile page's "Configure training sessions")."""
    grip_names = training_log.grip_names(session)
    dimension_names = training_log.grip_dimension_names(session)
    overrides = [
        {
            "grip_type_id": ps.grip_type_id,
            "edge_mm": ps.edge_mm,
            "grip_name": grip_names.get(ps.grip_type_id, "Unknown"),
            "dimension_name": dimension_names.get(ps.grip_type_id, "edge depth"),
            "path": PROGRESSION_LABELS.get(ps.path, ps.path),
            "rep_min": ps.rep_min,
            "rep_max": ps.rep_max,
            "max_sets": ps.max_sets,
        }
        for ps in _combo_overrides(session, user)
    ]
    return {
        "default": training_log.get_progression_settings(session, user),
        "overrides": overrides,
        "grip_types": session.exec(select(GripType).order_by(GripType.name)).all(),  # type: ignore[arg-type]
        "labels": PROGRESSION_LABELS,
    }
