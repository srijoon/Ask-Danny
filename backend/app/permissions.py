import re

EVERYONE = "everyone"
GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")


def principals_for(user):
    return [EVERYONE, f"user:{user['username']}", *(f"group:{g}" for g in user.get("groups", []))]


def parse_groups(values):
    if isinstance(values, str):
        values = [values]
    groups = set()
    for value in values:
        for name in value.split(","):
            name = name.strip().lower()
            if not name:
                continue
            if not GROUP_RE.match(name):
                raise ValueError(
                    f"Invalid group name '{name}': use lowercase letters, digits, '-' or '_'."
                )
            groups.add(name)
    return sorted(groups)


def document_access(groups, *, everyone, owner=None):
    if everyone:
        return [EVERYONE]
    access = [f"group:{g}" for g in parse_groups(groups)]
    if access and owner:
        access.append(f"user:{owner}")
    return access


def access_groups(access):
    return [p.split(":", 1)[1] for p in access if p.startswith("group:")]


def describe_access(access):
    if EVERYONE in access:
        return "Everyone"
    labels = [p.split(":", 1)[1] for p in access if p.startswith("group:")]
    labels += [f"{p.split(':', 1)[1]} (uploader)" for p in access if p.startswith("user:")]
    return ", ".join(labels) or "Nobody"
