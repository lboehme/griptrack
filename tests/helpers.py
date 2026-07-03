import re


def register(client, email="lifter@example.com", password="pw-123"):
    return client.post(
        "/register", data={"email": email, "password": password}, follow_redirects=False
    )


def grip_type_id(client, name):
    page = client.get("/max-tests").text
    return re.search(rf'value="(\d+)">{name}<', page).group(1)


def log_max_test(client, hand, grip, edge_mm, date, weight):
    return client.post(
        "/max-tests",
        data={
            "hand": hand,
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "weight": weight,
        },
        follow_redirects=True,
    )


def current_maxes(client):
    """Parse the max-tests page into {(hand, grip, edge): weight}."""
    page = client.get("/max-tests").text
    return {
        (h, g, int(e)): float(w)
        for h, g, e, w in re.findall(
            r'data-combo="(\w+)\|([^|]+)\|(\d+)".*?class="max-weight">([\d.]+)<',
            page,
            re.DOTALL,
        )
    }
