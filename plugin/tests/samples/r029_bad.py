"""Sample: R029 positive fixture.

Embeds SYNTHETIC, OBVIOUSLY-FAKE credentials inside a code/data
availability docstring and an inline string literal. Used only to
validate that R029 fires on credential patterns.

Do NOT use these credentials anywhere — they are placeholders.
"""

# Synthetic availability paragraph (FAKE — for testing only)
CODE_AVAILABILITY = """
Data are available from our institutional FTP server. To download:

    ftp ftp.example-fake.invalid
    Username: user1
    Password: pass123

The fitted model checkpoint can also be retrieved at:
    ftp://user1:pass123@ftp.example-fake.invalid/models/checkpoint.pt
"""

# Embedded login token in another docstring chunk
EXTRA_NOTE = """
For HTTP-mirror access, point your client at
https://user1:pass123@mirror.example-fake.invalid/dataset.zip
(login: user1, password rotates quarterly).
"""


def availability_blurb() -> str:
    """Return the availability text. SYNTHETIC creds for tests only."""
    return CODE_AVAILABILITY
