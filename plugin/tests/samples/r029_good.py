"""Sample: R029 negative fixture.

A clean code/data-availability blurb that uses a request-workflow rather
than embedding credentials. Should produce zero R029 diagnostics.
"""

# Clean availability paragraph — no credentials, points to a request workflow
CODE_AVAILABILITY = """
Code is available at https://github.com/example/project (MIT license).

De-identified patient-level data are NOT redistributed. To request
controlled access, submit a Data Use Agreement to data-access@example.org.
Approved researchers receive a per-user token via the institutional
access portal; tokens are scoped to a single project and auto-expire
after 12 months.
"""


def availability_blurb() -> str:
    """Return the availability text — no embedded credentials."""
    return CODE_AVAILABILITY


# Common code patterns that should NOT trigger R029:
def login_handler(user_id: str) -> dict:
    """Build an auth-handler payload. The string 'login' here is a key,
    not a credential disclosure."""
    return {"action": "login", "user_id": user_id}


def example_url() -> str:
    return "https://example.org/dataset.zip"
