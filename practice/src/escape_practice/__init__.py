"""Local Escape practice harness. Not the official AMD verify path.

PRACTICE_KEY is a public test vector for the control-plane practice signer.
It is not a secret, not a hotel key, and not an AMD ARK pin.
"""

SCHEMA = "escape_practice_claim_v0"
# Public HMAC test vector (control-plane practice signer). Not a secret.
PRACTICE_KEY = b"escape-practice-v0-not-a-hotel-key"
HOST_NONCE_PATH = "/host-nonce"
DEFAULT_TTL_SECONDS = 3600
DEFAULT_SWEEP_INTERVAL_SECONDS = 30
MAX_COMMANDS = 256
MAX_ARGV_LEN = 32
MAX_STDOUT_CHARS = 64_000
MAX_ID_LEN = 128
MAX_CLAIM_BYTES = 1_000_000
MAX_CLOCK_SKEW_SECONDS = 300
