import itertools
import re

from backend import plates
from backend.limits import MAX_WEIGHT
from backend.models import PlateInventoryItem
from tests.helpers import login, register, register_second_user


def expected_ladder(inventory, cap=MAX_WEIGHT):
    """Reference oracle: expand every plate into individual units and
    enumerate all subset sums directly (independent of the incremental
    set walk plates.loadable_ladder uses), rounding to cents like the production
    code to avoid float-accumulation mismatches."""
    units = [
        int(round(item.weight * 100))
        for item in inventory
        for _ in range(item.count)
    ]
    cap_cents = int(round(cap * 100))
    totals = {0}
    for r in range(1, len(units) + 1):
        for combo in itertools.combinations(units, r):
            total = sum(combo)
            if total <= cap_cents:
                totals.add(total)
    return sorted(total / 100 for total in totals)


def inventory_rows(client):
    """Parse the plates page into {weight: count}."""
    page = client.get("/plates").text
    return {
        float(w): int(c)
        for w, c in re.findall(
            r'class="plate-weight">([^<]+)</\w+>.*?'
            r'class="plate-count" data-count="(\d+)"',
            page,
            re.DOTALL,
        )
    }


def test_new_user_gets_a_seeded_default_inventory(client):
    register(client)

    rows = inventory_rows(client)

    assert rows, "expected a non-empty seeded inventory"
    # A sensible kg default must include small change and workhorse plates.
    assert 1.25 in rows
    assert 5.0 in rows
    assert all(count >= 1 for count in rows.values())


def test_lbs_user_gets_lbs_denominated_defaults(client):
    register(client, unit_pref="lbs")

    rows = inventory_rows(client)

    # 45 lb is the canonical big plate; 20 kg would make no sense here.
    assert 45.0 in rows
    assert 20.0 not in rows


def test_plate_inventory_is_scoped_to_the_logged_in_user(client):
    register(client, email="founder@example.com")
    client.post("/plates", data={"weight": "7.5", "count": "2"}, follow_redirects=True)

    register_second_user(client)

    # Logged in as friend: founder's custom 7.5 plate must not be there,
    # and removing a plate must not touch the founder's stack.
    assert 7.5 not in inventory_rows(client)
    client.post("/plates", data={"weight": "5", "count": "0"}, follow_redirects=True)

    client.post("/logout")
    login(client, "founder@example.com", "test-pw-1234")
    rows = inventory_rows(client)
    assert rows[7.5] == 2
    assert 5.0 in rows


def test_user_can_add_change_and_remove_plates(client):
    register(client)

    client.post("/plates", data={"weight": "7.5", "count": "2"}, follow_redirects=True)
    assert inventory_rows(client)[7.5] == 2

    client.post("/plates", data={"weight": "7.5", "count": "4"}, follow_redirects=True)
    assert inventory_rows(client)[7.5] == 4

    client.post("/plates", data={"weight": "7.5", "count": "0"}, follow_redirects=True)
    assert 7.5 not in inventory_rows(client)


def kg_inventory():
    return [
        PlateInventoryItem(weight=weight, count=count)
        for weight, count in plates.DEFAULT_INVENTORY["kg"]
    ]


def lbs_inventory():
    return [
        PlateInventoryItem(weight=weight, count=count)
        for weight, count in plates.DEFAULT_INVENTORY["lbs"]
    ]


def test_loadable_ladder_for_seeded_kg_default_inventory():
    inventory = kg_inventory()

    ladder = plates.loadable_ladder(inventory)

    assert ladder == expected_ladder(inventory)
    assert ladder == sorted(set(ladder)), "ladder must be ascending and deduped"
    assert ladder[0] == 0.0
    assert ladder[-1] == 58.5  # 2*0.5 + 2*1.25 + 2*2.5 + 2*5 + 2*10 + 20


def test_loadable_ladder_for_seeded_lbs_default_inventory():
    inventory = lbs_inventory()

    ladder = plates.loadable_ladder(inventory)

    assert ladder == expected_ladder(inventory)
    assert ladder == sorted(set(ladder)), "ladder must be ascending and deduped"
    assert ladder[0] == 0.0
    assert ladder[-1] == 132.5  # 2*1.25 + 2*2.5 + 2*5 + 2*10 + 2*25 + 45


def test_loadable_ladder_with_no_plates_returns_defined_fallback():
    assert plates.loadable_ladder([]) == [0.0]


def test_round_down_to_loadable_consumes_the_ladder():
    inventory = kg_inventory()

    # A target that isn't itself achievable rounds down to the nearest rung.
    assert plates.round_down_to_loadable(6.1, inventory) == 6.0
    # A target that is exactly achievable stays put.
    assert plates.round_down_to_loadable(5.5, inventory) == 5.5
    # A target above everything the pin can make caps at the ladder's top.
    assert plates.round_down_to_loadable(1000.0, inventory) == 58.5
    # Nothing fits below a negative target -> the documented 0.0 fallback.
    assert plates.round_down_to_loadable(-5.0, inventory) == 0.0


def test_loadable_ladder_is_bounded_by_the_weight_limit_for_a_pathological_inventory():
    # A user could in principle own many denominations with the max count
    # each; the ladder must stay bounded by MAX_WEIGHT (not by inventory
    # size) and the walk must stay fast -- this is the DoS-sensitive path.
    huge_inventory = [
        PlateInventoryItem(weight=weight, count=100)
        for weight in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)
    ]

    ladder = plates.loadable_ladder(huge_inventory)

    # Deterministic stand-in for a runtime assertion: achievable totals are
    # tracked in integer cents capped at MAX_WEIGHT, so the set (and thus the
    # ladder) can never exceed MAX_WEIGHT*100 + 1 entries regardless of how
    # large the inventory is -- this is what actually keeps the walk fast.
    assert len(ladder) <= int(MAX_WEIGHT * 100) + 1
    assert ladder[0] == 0.0
    assert ladder[-1] <= MAX_WEIGHT
    assert all(rung <= MAX_WEIGHT for rung in ladder)
    assert ladder == sorted(set(ladder))
