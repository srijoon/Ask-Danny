# The access-control vocabulary: users have principals ("everyone",
# "user:<name>", "group:<name>") and documents/chunks carry a list of them.
# Retrieval and the /api/files endpoints both authorise by intersecting them.
import re

# access control is tag matching, not roles: a chunk/document carries a list of
# principal strings, and a user can read it when the lists intersect
EVERYONE = "everyone"
# group names end up inside principal strings and URLs; keep them boring on purpose
GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")


def principals_for(user):
    """Every principal tag a user carries: everyone + user:<name> + group:<g> each."""
    # every signed-in user matches "everyone", plus themselves and each of their groups
    return [EVERYONE, f"user:{user['username']}", *(f"group:{g}" for g in user.get("groups", []))]


def parse_groups(values):
    """Normalize group input (str or list, comma-separated) into sorted valid names."""
    # callers pass "a,b" (one form field) or ["a","b"] (checkboxes); accept a mix of both
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
    """Build the access list stored on a document and its chunks at upload time."""
    if everyone:
        return [EVERYONE]
    access = [f"group:{g}" for g in parse_groups(groups)]
    # the uploader keeps read access to their own file even if they later leave
    # the group — a group-only list could lock them out of something they added
    if access and owner:
        access.append(f"user:{owner}")
    return access


def access_groups(access):
    """Pull just the group names out of an access list (admin pages + /api/admin/groups)."""
    return [p.split(":", 1)[1] for p in access if p.startswith("group:")]


def describe_access(access):
    """Human label for an access list on the admin page ("Everyone", "hr, finance", "Nobody")."""
    # human label for the admin page: "Everyone", "hr, finance", or "Nobody"
    if EVERYONE in access:
        return "Everyone"
    labels = [p.split(":", 1)[1] for p in access if p.startswith("group:")]
    labels += [f"{p.split(':', 1)[1]} (uploader)" for p in access if p.startswith("user:")]
    return ", ".join(labels) or "Nobody"
