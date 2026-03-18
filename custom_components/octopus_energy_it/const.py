"""Constants for the Octopus Energy Italy integration."""

DOMAIN = "octopus_energy_it"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # nosec B105 — config key name, not a hardcoded credential

# Debug interval settings
UPDATE_INTERVAL = 1  # Update interval in minutes

# Token management
TOKEN_REFRESH_MARGIN = (
    300  # Refresh token if less than 300 seconds (5 minutes) remaining
)
TOKEN_AUTO_REFRESH_INTERVAL = 50 * 60  # Auto refresh token every 50 minutes

# Login retry settings
LOGIN_RETRIES = 5
LOGIN_INITIAL_DELAY = 1  # seconds
LOGIN_MAX_DELAY = 30  # seconds

# Debug options
DEBUG_ENABLED = False
LOG_API_RESPONSES = False  # Set to True to log full API responses
LOG_TOKEN_RESPONSES = (
    False  # Set to True to log token-related responses (login, refresh)
)
