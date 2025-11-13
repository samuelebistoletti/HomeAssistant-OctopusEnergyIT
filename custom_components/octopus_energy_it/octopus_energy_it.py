"""
Provide the OctopusEnergyIT class for interacting with the Octopus Energy API.

Includes methods for authentication, fetching account details, managing devices, and retrieving
various data related to electricity usage and tariffs.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

import jwt
from homeassistant.exceptions import ConfigEntryNotReady
from python_graphql_client import GraphqlClient

from .const import LOG_API_RESPONSES, LOG_TOKEN_RESPONSES, TOKEN_AUTO_REFRESH_INTERVAL, TOKEN_REFRESH_MARGIN

_LOGGER = logging.getLogger(__name__)

GRAPH_QL_ENDPOINT = "https://api.oeit-kraken.energy/v1/graphql/"
ELECTRICITY_LEDGER = "ELECTRICITY_LEDGER"

# Global token manager to prevent multiple instances from making redundant token requests
# Comprehensive query that gets all data in one go
COMPREHENSIVE_QUERY = """
query ComprehensiveDataQuery($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    id
    ledgers {
      balance
      ledgerType
    }
    properties {
      id
      electricitySupplyPoints {
        id
        pod
        status
        enrolmentStatus
        enrolmentStartDate
        supplyStartDate
        cancellationReason
        isSmartMeter
        product {
          __typename
          ... on ElectricityProductType {
            code
            description
            displayName
            fullName
            termsAndConditionsUrl
            validTo
            params {
              productType
              annualStandingCharge
              consumptionCharge
              consumptionChargeF2
              consumptionChargeF3
            }
            prices {
              productType
              annualStandingCharge
              annualStandingChargeUnits
              consumptionCharge
              consumptionChargeF2
              consumptionChargeF3
              consumptionChargeUnits
            }
          }
        }
        agreements(first: 10) {
          edges {
            node {
              id
              validFrom
              validTo
              agreedAt
              terminatedAt
              isActive
              product {
                __typename
                ... on ElectricityProductType {
                  code
                  description
                  displayName
                  fullName
                  termsAndConditionsUrl
                  validTo
                  params {
                    productType
                    annualStandingCharge
                    consumptionCharge
                    consumptionChargeF2
                    consumptionChargeF3
                  }
                  prices {
                    productType
                    annualStandingCharge
                    annualStandingChargeUnits
                    consumptionCharge
                    consumptionChargeF2
                    consumptionChargeF3
                    consumptionChargeUnits
                  }
                }
              }
            }
          }
        }
      }
      gasSupplyPoints {
        id
        pdr
        status
        enrolmentStatus
        enrolmentStartDate
        supplyStartDate
        cancellationReason
        isSmartMeter
        product {
          __typename
          ... on GasProductType {
            code
            description
            displayName
            fullName
            termsAndConditionsUrl
            validTo
            params {
              productType
              annualStandingCharge
              consumptionCharge
            }
            prices {
              annualStandingCharge
              consumptionCharge
            }
          }
        }
        agreements(first: 10) {
          edges {
            node {
              id
              validFrom
              validTo
              agreedAt
              terminatedAt
              isActive
              product {
                __typename
                ... on GasProductType {
                  code
                  description
                  displayName
                  fullName
                  termsAndConditionsUrl
                  validTo
                  params {
                    productType
                    annualStandingCharge
                    consumptionCharge
                  }
                  prices {
                    annualStandingCharge
                    consumptionCharge
                  }
                }
              }
            }
          }
        }
      }
    }
  }
  completedDispatches(accountNumber: $accountNumber) {
    delta
    deltaKwh
    end
    endDt
    meta {
      location
      source
    }
    start
    startDt
  }
  devices(accountNumber: $accountNumber) {
    status {
      current
      currentState
      isSuspended
    }
    provider
    preferences {
      mode
      schedules {
        dayOfWeek
        max
        min
        time
      }
      targetType
      unit
      gridExport
    }
    preferenceSetting {
      deviceType
      id
      mode
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
      unit
    }
    name
    integrationDeviceId
    id
    deviceType
    alerts {
      message
      publishedAt
    }
    ... on SmartFlexVehicle {
      id
      name
      status {
        current
        currentState
        isSuspended
      }
      vehicleVariant {
        model
        batterySize
      }
    }
  }
}
"""

# Query to get latest gas meter readings
GAS_METER_READINGS_QUERY = """
query GasMeterReadings(
  $accountNumber: String!
  $pdr: String!
  $dateFrom: Date
  $dateTo: Date
  $first: Int
  $last: Int
) {
  gasMeterReadings(
    accountNumber: $accountNumber
    pdr: $pdr
    dateFrom: $dateFrom
    dateTo: $dateTo
    first: $first
    last: $last
  ) {
    edges {
      node {
        readingDate
        readingType
        readingSource
        consumptionValue
      }
    }
  }
}
"""

# Query to get electricity measurements for a supply point
PROPERTY_ELECTRICITY_MEASUREMENTS_QUERY = """
query ElectricityMeasurements(
  $propertyId: ID!
  $pod: String!
  $startOn: Date
  $endOn: Date
  $first: Int
  $last: Int
) {
  property(id: $propertyId) {
    measurements(
      startOn: $startOn
      endOn: $endOn
      first: $first
      last: $last
      utilityFilters: [
        {
          electricityFilters: {
            marketSupplyPointId: $pod
            readingFrequencyType: POINT_IN_TIME
            readingDirection: CONSUMPTION
          }
        }
      ]
    ) {
      edges {
        node {
          value
          unit
          readAt
          source
        }
      }
    }
  }
}
"""


# Query to get vehicle device details with preference settings
VEHICLE_DETAILS_QUERY = """
query Vehicle($accountNumber: String = "") {
  devices(accountNumber: $accountNumber) {
    deviceType
    id
    integrationDeviceId
    name
    preferenceSetting {
      deviceType
      id
      mode
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
      unit
    }
    preferences {
      gridExport
      mode
      targetType
      unit
    }
  }
}
"""

# Simple account discovery query
ACCOUNT_DISCOVERY_QUERY = """
query {
  viewer {
    accounts {
      number
      ledgers {
        balance
        ledgerType
      }
    }
  }
}
"""



SET_DEVICE_PREFERENCES_MUTATION = """
mutation SetDevicePreferences($input: SmartFlexDevicePreferencesInput!) {
  setDevicePreferences(input: $input) {
    id
  }
}
"""

DEVICE_SUSPENSION_MUTATION = """
mutation UpdateDeviceSmartControl($input: SmartControlInput!) {
  updateDeviceSmartControl(input: $input) {
    id
  }
}
"""

FLEX_PLANNED_DISPATCHES_QUERY = """
query FlexPlannedDispatches($deviceId: String!) {
  flexPlannedDispatches(deviceId: $deviceId) {
    end
    energyAddedKwh
    start
    type
  }
}
"""



class TokenManager:
    """Store and validate auth token details."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expiry: float | None = None

    @property
    def token(self) -> str | None:
        """Return the current token, if any."""
        return self._token

    @property
    def expiry(self) -> float | None:
        """Return the token expiry timestamp."""
        return self._expiry

    @property
    def is_valid(self) -> bool:
        """Return True when a token exists and is not close to expiry."""
        if not self._token:
            return False

        if self._expiry is None:
            return True

        now = datetime.now(UTC).timestamp()
        if now >= self._expiry - TOKEN_REFRESH_MARGIN:
            _LOGGER.debug(
                "Token validity check: INVALID (expires in %s seconds)",
                int(self._expiry - now),
            )
            return False

        return True

    def set_token(self, token: str, expiry: float | None = None) -> None:
        """Store a new token and calculate its expiry."""
        self._token = token

        if expiry is not None:
            self._expiry = float(expiry)
            return

        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp = decoded.get("exp")
            self._expiry = float(exp) if exp is not None else None
        except Exception as exc:
            now = datetime.now(UTC).timestamp()
            self._expiry = now + TOKEN_AUTO_REFRESH_INTERVAL
            _LOGGER.debug(
                "Unable to decode token expiry (%s). Falling back to %s minutes.",
                exc,
                TOKEN_AUTO_REFRESH_INTERVAL // 60,
            )

    def clear(self) -> None:
        """Forget the current token."""
        self._token = None
        self._expiry = None


class OctopusEnergyIT:
    def __init__(self, email: str, password: str):
        """
        Initialize the OctopusEnergyIT API client.

        Args:
            email: The email address for the Octopus Energy Italy account
            password: The password for the Octopus Energy Italy account

        """
        self._email = email
        self._password = password

        self._token_manager = TokenManager()
        self._login_lock = asyncio.Lock()

    @property
    def _token(self):
        """Get the current token from the token manager."""
        return self._token_manager.token

    def _get_auth_headers(self):
        """Get headers with authorization token."""
        return {"Authorization": self._token} if self._token else {}

    def _get_graphql_client(self, *, use_auth: bool = True, additional_headers=None):
        """Return a GraphQL client configured with optional auth headers."""
        headers = self._get_auth_headers() if use_auth else {}
        if additional_headers:
            headers.update(additional_headers)
        return GraphqlClient(endpoint=GRAPH_QL_ENDPOINT, headers=headers)


    async def _execute_graphql(
        self,
        query: str,
        variables: dict | None = None,
        *,
        require_auth: bool = True,
        retry_on_token_error: bool = True,
    ) -> dict | None:
        """Execute a GraphQL request with optional auth and retry handling."""
        if require_auth and not await self.ensure_token():
            _LOGGER.error("Cannot execute GraphQL query without a valid token")
            return None

        client = self._get_graphql_client(use_auth=require_auth)
        try:
            response = await client.execute_async(
                query=query,
                variables=variables or {},
            )
        except Exception as exc:
            _LOGGER.error("GraphQL request failed: %s", exc)
            return None

        if (
            require_auth
            and retry_on_token_error
            and isinstance(response, dict)
            and any(
                (error or {}).get("extensions", {}).get("errorCode") == "KT-CT-1124"
                for error in response.get("errors", [])
            )
        ):
            _LOGGER.warning("Token expired during GraphQL request; refreshing and retrying")
            self._token_manager.clear()
            if await self.login():
                return await self._execute_graphql(
                    query,
                    variables,
                    require_auth=require_auth,
                    retry_on_token_error=False,
                )
            return None

        return response

    async def login(self) -> bool:
            """Login and obtain a new token."""
            # Import constants for logging options

            # Use a lock to prevent multiple concurrent login attempts
            async with self._login_lock:
                # Check if token is still valid after waiting for the lock
                if self._token_manager.is_valid:
                    _LOGGER.debug("Token still valid after lock, skipping login")
                    return True

                query = """
                    mutation krakenTokenAuthentication($email: String!, $password: String!) {
                      obtainKrakenToken(input: { email: $email, password: $password }) {
                        token
                        payload
                      }
                    }
                """
                variables = {"email": self._email, "password": self._password}
                retries = 5  # Reduced from 10 to 5 retries for simpler logic
                attempt = 0
                delay = 1  # Start with 1 second delay
                max_delay = 30  # Cap the delay at 30 seconds

                while attempt < retries:
                    attempt += 1
                    try:
                        _LOGGER.debug("Making login attempt %s of %s", attempt, retries)
                        response = await self._execute_graphql(
                            query=query,
                            variables=variables,
                            require_auth=False,
                            retry_on_token_error=False,
                        )

                        # Log token response when LOG_TOKEN_RESPONSES is enabled
                        if LOG_TOKEN_RESPONSES:
                            # Create a safe copy of the response for logging
                            import copy

                            safe_response = copy.deepcopy(response)
                            if isinstance(safe_response, dict):
                                # Check if we have a token in the response and mask most of it for logging
                                token_container = (
                                    safe_response.get("data", {}).get("obtainKrakenToken")
                                )
                                if isinstance(token_container, dict) and "token" in (
                                    token_container
                                ):
                                    token = token_container["token"]
                                    if token and len(token) > 10:
                                        # Keep first 5 and last 5 chars, mask the rest
                                        mask_length = len(token) - 10
                                        masked_token = (
                                            token[:5] + "*" * mask_length + token[-5:]
                                        )
                                        token_container["token"] = masked_token
                            _LOGGER.info(
                                "Token response (partial): %s",
                                json.dumps(safe_response, indent=2),
                            )

                        if not isinstance(response, dict):
                            _LOGGER.error(
                                "Unexpected login response type at attempt %s: %s",
                                attempt,
                                response,
                            )
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, max_delay)
                            continue

                        if "errors" in response:
                            first_error = response["errors"][0]
                            extensions = first_error.get("extensions", {})
                            error_code = extensions.get("errorCode")
                            error_message = first_error.get("message", "Unknown error")

                            if error_code == "KT-CT-1138":  # Invalid credentials
                                _LOGGER.error(
                                    "Login failed: %s (attempt %s of %s). The credentials appear to be invalid; aborting further attempts.",
                                    error_message,
                                    attempt,
                                    retries,
                                )
                                return False

                            if error_code == "KT-CT-1199":  # Too many requests
                                _LOGGER.warning(
                                    "Rate limit hit. Retrying in %s seconds... (attempt %s of %s)",
                                    delay,
                                    attempt,
                                    retries,
                                )
                                await asyncio.sleep(delay)
                                delay = min(
                                    delay * 2, max_delay
                                )  # Exponential backoff with max cap
                                continue
                            _LOGGER.error(
                                "Login failed: %s (attempt %s of %s)",
                                error_message,
                                attempt,
                                retries,
                            )
                            # For other types of errors, continue with retries
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, max_delay)
                            continue

                        if "data" in response and "obtainKrakenToken" in response["data"]:
                            token_data = response["data"]["obtainKrakenToken"]
                            token = token_data.get("token")
                            payload = token_data.get("payload")

                            if token:
                                # Pass both token and expiration time to the token manager
                                if (
                                    payload
                                    and isinstance(payload, dict)
                                    and "exp" in payload
                                ):
                                    expiration = payload["exp"]
                                    self._token_manager.set_token(token, expiration)
                                else:
                                    # Fall back to JWT decoding if no payload available
                                    self._token_manager.set_token(token)

                                return True
                            _LOGGER.error(
                                "No token in response despite successful request (attempt %s of %s)",
                                attempt,
                                retries,
                            )
                        else:
                            _LOGGER.error(
                                "Unexpected API response format at attempt %s: %s",
                                attempt,
                                response,
                            )

                        # If we got here with an invalid response, try again
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, max_delay)

                    except Exception as e:
                        _LOGGER.error("Error during login attempt %s: %s", attempt, e)
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, max_delay)

                _LOGGER.error("All %s login attempts failed.", retries)
                return False

    async def ensure_token(self):
            """Ensure a valid token is available, refreshing if necessary."""
            if not self._token_manager.is_valid:
                _LOGGER.debug("Token invalid or expired, logging in again")
                return await self.login()
            return True

        # Consolidated query to get both accounts list and initial data in one API call

    async def fetch_accounts_with_initial_data(self):
        """Fetch accounts and initial data in a single API call."""
        response = await self._execute_graphql(ACCOUNT_DISCOVERY_QUERY)

        if not isinstance(response, dict):
            _LOGGER.error("Unexpected API response structure: %s", response)
            return None

        if "data" in response and "viewer" in response["data"]:
            accounts = response["data"]["viewer"].get("accounts") or []
            if not accounts:
                _LOGGER.error("No accounts found")
                return None
            return accounts

        errors = response.get("errors") if isinstance(response, dict) else None
        if errors:
            _LOGGER.error("GraphQL errors fetching accounts: %s", errors)
        return None


    async def accounts(self):
            """Fetch account numbers."""
            accounts = await self.fetch_accounts_with_initial_data()
            if not accounts:
                _LOGGER.error("Failed to fetch accounts")
                raise ConfigEntryNotReady("Failed to fetch accounts")

            return [account["number"] for account in accounts]

    async def fetch_accounts(self):
            """Fetch accounts data."""
            return await self.fetch_accounts_with_initial_data()

        # Comprehensive data fetch in a single query
    async def fetch_all_data(self, account_number: str):
            """
            Fetch all data for an account including devices, dispatches and account details.

            This comprehensive query consolidates multiple separate queries into one
            to minimize API calls and improve performance.
            """
            variables = {"accountNumber": account_number}

            try:
                _LOGGER.debug(
                    "Making API request to fetch_all_data for account %s",
                    account_number,
                )
                response = await self._execute_graphql(
                    COMPREHENSIVE_QUERY,
                    variables=variables,
                )

                if response is None:
                    _LOGGER.error("API returned None response")
                    return None

                if LOG_API_RESPONSES:
                    _LOGGER.info("API Response: %s", json.dumps(response, indent=2))
                else:
                    _LOGGER.debug(
                        "API request completed. Set LOG_API_RESPONSES=True for full response logging"
                    )

                # Initialize the result structure - note that 'products' is an empty list
                # since we removed that field from the query
                result = {
                    "account": {},
                    "products": [],  # This will stay empty as we removed the property field
                    "completedDispatches": [],
                    "devices": [],
                    "plannedDispatches": [],
                    "gas_products": [],
                }

                # Process the GraphQL response, tolerate partial data when possible
                if "data" in response:
                    data = response["data"]

                    account_payload = data.get("account")
                    if account_payload:
                        self.normalise_account_properties(account_payload)
                        result["account"] = account_payload

                        electricity_products = self.extract_electricity_products(account_payload)
                        if electricity_products:
                            result["products"] = electricity_products
                            _LOGGER.debug(
                                "Extracted %d electricity products from account data",
                                len(electricity_products),
                            )
                        gas_products = self.extract_gas_products(account_payload)
                        if gas_products:
                            result["gas_products"] = gas_products
                            _LOGGER.debug(
                                "Extracted %d gas products from account data",
                                len(gas_products),
                            )
                    else:
                        _LOGGER.debug("No account payload returned in response")

                    result["devices"] = data.get("devices") or []
                    result["completedDispatches"] = data.get("completedDispatches") or []

                    # Fetch flex planned dispatches for all devices with the new API
                    result["plannedDispatches"] = []
                    if result["devices"]:
                        _LOGGER.debug(
                            "Fetching flex planned dispatches for %d devices",
                            len(result["devices"]),
                        )
                        for device in result["devices"]:
                            device_id = device.get("id")
                            device_name = device.get("name", "Unknown")
                            if device_id:
                                try:
                                    flex_dispatches = (
                                        await self.fetch_flex_planned_dispatches(device_id)
                                    )
                                    if flex_dispatches:
                                        # Transform the new API format to match the old format for backward compatibility
                                        for dispatch in flex_dispatches:
                                            # Map new fields to old field names where possible
                                            transformed_dispatch = {
                                                "start": dispatch.get("start"),
                                                "startDt": dispatch.get(
                                                    "start"
                                                ),  # Same as start
                                                "end": dispatch.get("end"),
                                                "endDt": dispatch.get("end"),  # Same as end
                                                "deltaKwh": dispatch.get("energyAddedKwh"),
                                                "delta": dispatch.get(
                                                    "energyAddedKwh"
                                                ),  # Same as deltaKwh
                                                "type": dispatch.get(
                                                    "type", "UNKNOWN"
                                                ),  # Add type as top-level attribute
                                                "meta": {
                                                    "source": "flex_api",
                                                    "type": dispatch.get("type", "UNKNOWN"),
                                                    "deviceId": device_id,
                                                },
                                            }
                                            result["plannedDispatches"].append(
                                                transformed_dispatch
                                            )
                                        _LOGGER.debug(
                                            "Added %d flex planned dispatches from device %s (%s)",
                                            len(flex_dispatches),
                                            device_id,
                                            device_name,
                                        )
                                except Exception as e:
                                    _LOGGER.warning(
                                        "Failed to fetch flex planned dispatches for device %s: %s",
                                        device_id,
                                        e,
                                    )
                    else:
                        _LOGGER.debug(
                            "No devices found, skipping flex planned dispatches fetch"
                        )

                    # Only log errors but don't fail the whole request if we got at least account data
                    if "errors" in response and result["account"]:
                        # Filter only the errors that are about missing devices or dispatches
                        non_critical_errors = [
                            error
                            for error in response["errors"]
                            if (
                                error.get("path", [])
                                and error.get("path")[0]
                                in ["completedDispatches", "devices"]
                                and error.get("extensions", {}).get("errorCode")
                                == "KT-CT-4301"
                            )
                        ]

                        # Handle other errors that might affect the account data
                        other_errors = [
                            error
                            for error in response["errors"]
                            if error not in non_critical_errors
                        ]

                        if non_critical_errors:
                            _LOGGER.warning(
                                "API returned non-critical errors (expected for accounts without devices/dispatches): %s",
                                non_critical_errors,
                            )

                        if other_errors:
                            _LOGGER.error("API returned critical errors: %s", other_errors)

                            # Check for token expiry in the other errors
                            for error in other_errors:
                                error_code = error.get("extensions", {}).get("errorCode")
                                if error_code == "KT-CT-1124":  # JWT expired
                                    _LOGGER.warning("Token expired, refreshing...")
                                    self._token_manager.clear()
                                    success = await self.login()
                                    if success:
                                        # Retry with new token
                                        return await self.fetch_all_data(account_number)

                    return result
                if "errors" in response:
                    # Handle critical errors that prevent any data from being returned
                    error = response.get("errors", [{}])[0]
                    error_code = error.get("extensions", {}).get("errorCode")

                    # Check if token expired error
                    if error_code == "KT-CT-1124":  # JWT expired
                        _LOGGER.warning("Token expired, refreshing...")
                        self._token_manager.clear()
                        success = await self.login()
                        if success:
                            # Retry with new token
                            return await self.fetch_all_data(account_number)

                    _LOGGER.error(
                        "API returned critical errors with no data: %s",
                        response.get("errors"),
                    )
                    return None
                _LOGGER.error("API response contains neither data nor errors")
                return None

            except Exception as e:
                _LOGGER.error("Error fetching all data: %s", e)
                return None

    @staticmethod
    def flatten_connection(connection):
            """Convert Relay-style connections to plain lists of nodes."""
            if isinstance(connection, dict):
                edges = connection.get("edges") or []
                nodes = [edge.get("node") for edge in edges if edge and edge.get("node")]
                return nodes
            return connection if isinstance(connection, list) else []

    def normalise_account_properties(self, account_data):
            """Ensure property collections are usable within Home Assistant."""
            properties = account_data.get("properties") or []
            account_data["properties"] = properties

            for property_data in properties:
                for key in ("electricitySupplyPoints", "gasSupplyPoints"):
                    supply_points = property_data.get(key) or []
                    property_data[key] = supply_points

                    for supply_point in supply_points:
                        agreements = supply_point.get("agreements")
                        supply_point["agreements"] = self.flatten_connection(agreements)

    @staticmethod
    def to_float_or_none(value):
            """Best-effort conversion of API decimal values to floats."""
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            try:
                return float(str(value))
            except (TypeError, ValueError):
                return None

    @staticmethod
    def format_cents_from_eur(amount):
            """Convert an amount in EUR/kWh to a string of cents for legacy consumers."""
            if amount is None:
                return "0"
            try:
                cents = float(amount) * 100.0
                formatted = f"{cents:.6f}".rstrip("0").rstrip(".")
                return formatted or "0"
            except (TypeError, ValueError):
                return "0"

    def build_electricity_product_entry(self, supply_point, agreement):
            """Create a simplified product descriptor for electricity tariffs."""
            product = {}
            valid_from = None
            valid_to = None
            agreement_id = None

            if agreement:
                product = agreement.get("product") or {}
                valid_from = agreement.get("validFrom")
                valid_to = agreement.get("validTo")
                agreement_id = agreement.get("id")
            else:
                product = supply_point.get("product") or {}

            if not product:
                return None

            params = product.get("params") or {}
            prices = product.get("prices") or {}

            def pick_value(key):
                if prices.get(key) is not None:
                    return prices.get(key)
                if params.get(key) is not None:
                    return params.get(key)
                return None

            base_rate = self.to_float_or_none(pick_value("consumptionCharge"))
            f2_rate = self.to_float_or_none(pick_value("consumptionChargeF2"))
            f3_rate = self.to_float_or_none(pick_value("consumptionChargeF3"))
            annual_charge = self.to_float_or_none(pick_value("annualStandingCharge"))
            units = pick_value("consumptionChargeUnits")
            annual_units = pick_value("annualStandingChargeUnits")

            product_type = params.get("productType") or prices.get("productType") or ""
            normalised_type = product_type.lower() if isinstance(product_type, str) else ""
            is_time_of_use = any(rate is not None for rate in (f2_rate, f3_rate)) or normalised_type in {
                "time_of_use",
                "timeofuse",
                "tou",
            }

            entry = {
                "code": product.get("code"),
                "description": product.get("description"),
                "name": product.get("fullName") or product.get("displayName"),
                "displayName": product.get("displayName"),
                "validFrom": valid_from,
                "validTo": valid_to,
                "agreementId": agreement_id,
                "productType": product_type,
                "isTimeOfUse": is_time_of_use,
                "type": "TimeOfUse" if is_time_of_use else "Simple",
                "timeslots": [],
                "termsAndConditionsUrl": product.get("termsAndConditionsUrl"),
                "pricing": {
                    "base": base_rate,
                    "f2": f2_rate,
                    "f3": f3_rate,
                    "units": units,
                    "annualStandingCharge": annual_charge,
                    "annualStandingChargeUnits": annual_units,
                },
                "params": params,
                "rawPrices": prices,
                "supplyPoint": {
                    "id": supply_point.get("id"),
                    "pod": supply_point.get("pod"),
                    "status": supply_point.get("status"),
                    "enrolmentStatus": supply_point.get("enrolmentStatus"),
                    "enrolmentStartDate": supply_point.get("enrolmentStartDate"),
                    "supplyStartDate": supply_point.get("supplyStartDate"),
                    "isSmartMeter": supply_point.get("isSmartMeter"),
                    "cancellationReason": supply_point.get("cancellationReason"),
                },
                "unitRateForecast": [],
            }

            entry["grossRate"] = self.format_cents_from_eur(base_rate)

            return entry

    def build_gas_product_entry(self, supply_point, agreement):
            """Create a simplified product descriptor for gas tariffs."""
            product = {}
            valid_from = None
            valid_to = None
            agreement_id = None

            if agreement:
                product = agreement.get("product") or {}
                valid_from = agreement.get("validFrom")
                valid_to = agreement.get("validTo")
                agreement_id = agreement.get("id")
            else:
                product = supply_point.get("product") or {}

            if not product:
                return None

            params = product.get("params") or {}
            prices = product.get("prices") or {}

            def pick_value(key):
                if prices.get(key) is not None:
                    return prices.get(key)
                if params.get(key) is not None:
                    return params.get(key)
                return None

            base_rate = self.to_float_or_none(pick_value("consumptionCharge"))
            annual_charge = self.to_float_or_none(pick_value("annualStandingCharge"))

            entry = {
                "code": product.get("code"),
                "description": product.get("description"),
                "name": product.get("fullName") or product.get("displayName"),
                "displayName": product.get("displayName"),
                "validFrom": valid_from,
                "validTo": valid_to,
                "agreementId": agreement_id,
                "termsAndConditionsUrl": product.get("termsAndConditionsUrl"),
                "pricing": {
                    "base": base_rate,
                    "units": params.get("consumptionChargeUnits"),
                    "annualStandingCharge": annual_charge,
                },
                "params": params,
                "rawPrices": prices,
                "supplyPoint": {
                    "id": supply_point.get("id"),
                    "pdr": supply_point.get("pdr"),
                    "status": supply_point.get("status"),
                    "enrolmentStatus": supply_point.get("enrolmentStatus"),
                    "enrolmentStartDate": supply_point.get("enrolmentStartDate"),
                    "supplyStartDate": supply_point.get("supplyStartDate"),
                    "isSmartMeter": supply_point.get("isSmartMeter"),
                    "cancellationReason": supply_point.get("cancellationReason"),
                },
            }

            entry["grossRate"] = self.format_cents_from_eur(base_rate)

            return entry

    def extract_gas_products(self, account_data):
            """Collect gas products from the account payload."""
            products = []
            seen_keys = set()

            for property_data in account_data.get("properties") or []:
                for supply_point in property_data.get("gasSupplyPoints") or []:
                    agreements = supply_point.get("agreements") or []

                    if agreements:
                        for agreement in agreements:
                            entry = self.build_gas_product_entry(supply_point, agreement)
                            if entry:
                                key = (
                                    entry.get("code"),
                                    entry.get("validFrom"),
                                    entry.get("validTo"),
                                    entry.get("agreementId"),
                                    entry.get("supplyPoint", {}).get("id"),
                                )
                                if key not in seen_keys:
                                    seen_keys.add(key)
                                    products.append(entry)
                    else:
                        entry = self.build_gas_product_entry(supply_point, None)
                        if entry:
                            key = (
                                entry.get("code"),
                                entry.get("validFrom"),
                                entry.get("validTo"),
                                entry.get("agreementId"),
                                entry.get("supplyPoint", {}).get("id"),
                            )
                            if key not in seen_keys:
                                seen_keys.add(key)
                                products.append(entry)

            return products

    def extract_electricity_products(self, account_data):
            """Collect electricity products from the account payload."""
            products = []
            seen_keys = set()

            for property_data in account_data.get("properties") or []:
                for supply_point in property_data.get("electricitySupplyPoints") or []:
                    agreements = supply_point.get("agreements") or []

                    if agreements:
                        for agreement in agreements:
                            entry = self.build_electricity_product_entry(
                                supply_point, agreement
                            )
                            if entry:
                                key = (
                                    entry.get("code"),
                                    entry.get("validFrom"),
                                    entry.get("validTo"),
                                    entry.get("agreementId"),
                                    entry.get("supplyPoint", {}).get("id"),
                                )
                                if key not in seen_keys:
                                    seen_keys.add(key)
                                    products.append(entry)
                    else:
                        entry = self.build_electricity_product_entry(supply_point, None)
                        if entry:
                            key = (
                                entry.get("code"),
                                entry.get("validFrom"),
                                entry.get("validTo"),
                                entry.get("agreementId"),
                                entry.get("supplyPoint", {}).get("id"),
                            )
                            if key not in seen_keys:
                                seen_keys.add(key)
                                products.append(entry)

            return products


    async def change_device_suspension(self, device_id: str, action: str):
        """Change device suspension state."""
        payload = {"input": {"deviceId": device_id, "action": action}}
        _LOGGER.debug(
            "Executing change_device_suspension: device_id=%s, action=%s",
            device_id,
            action,
        )

        response = await self._execute_graphql(
            DEVICE_SUSPENSION_MUTATION,
            variables=payload,
        )

        if not isinstance(response, dict):
            _LOGGER.error("Invalid response while changing device suspension: %s", response)
            return None

        if errors := response.get("errors"):
            first_error = errors[0] if errors else {}
            error_code = first_error.get("extensions", {}).get("errorCode")
            error_message = first_error.get("message", "Unknown error")
            _LOGGER.error(
                "API returned errors when changing device suspension: %s (code: %s)",
                error_message,
                error_code,
            )
            return None

        return (
            response.get("data", {})
            .get("updateDeviceSmartControl", {})
            .get("id")
        )



    async def set_device_preferences(
        self,
        device_id: str,
        target_percentage: int,
        target_time: str,
    ) -> bool:
        """Set device charging preferences using the SmartFlex API."""
        if not await self.ensure_token():
            _LOGGER.error("Failed to ensure valid token for set_device_preferences")
            return False

        original_percentage = target_percentage
        target_percentage = int(round(target_percentage))
        target_percentage = max(10, min(100, target_percentage))
        if target_percentage != original_percentage:
            _LOGGER.debug(
                "Adjusted target percentage from %s to %s to satisfy API constraints",
                original_percentage,
                target_percentage,
            )

        try:
            formatted_time = self.format_time_to_hh_mm(target_time)
            hour = int(formatted_time.split(":")[0])
            if not 4 <= hour <= 17:
                _LOGGER.error(
                    "Invalid target time: %s. Must be between 04:00 and 17:00.",
                    formatted_time,
                )
                return False
        except ValueError as exc:
            _LOGGER.error("Time format validation error: %s", exc)
            return False

        days = [
            "MONDAY",
            "TUESDAY",
            "WEDNESDAY",
            "THURSDAY",
            "FRIDAY",
            "SATURDAY",
            "SUNDAY",
        ]
        schedules = [
            {"dayOfWeek": day, "time": formatted_time, "max": target_percentage}
            for day in days
        ]

        variables = {
            "input": {
                "deviceId": device_id,
                "mode": "CHARGE",
                "unit": "PERCENTAGE",
                "schedules": schedules,
            }
        }

        _LOGGER.debug(
            "Making set_device_preferences API request with device_id: %s, target: %s%%, time: %s",
            device_id,
            target_percentage,
            formatted_time,
        )

        response = await self._execute_graphql(
            SET_DEVICE_PREFERENCES_MUTATION,
            variables=variables,
        )

        if not isinstance(response, dict):
            _LOGGER.error("Invalid response setting device preferences: %s", response)
            return False

        if errors := response.get("errors"):
            first_error = errors[0] if errors else {}
            error_code = first_error.get("extensions", {}).get("errorCode")
            error_message = first_error.get("message", "Unknown error")
            _LOGGER.error(
                "API error setting device preferences: %s (code: %s)",
                error_message,
                error_code,
            )
            return False

        return True



    async def get_vehicle_devices(self, account_number: str):
        """Return SmartFlex vehicle devices for a given account."""
        response = await self._execute_graphql(
            VEHICLE_DETAILS_QUERY,
            variables={"accountNumber": account_number},
        )

        if not isinstance(response, dict):
            _LOGGER.error("Invalid response fetching vehicle devices: %s", response)
            return None

        if errors := response.get("errors"):
            _LOGGER.error("GraphQL errors in vehicle devices response: %s", errors)
            return None

        devices = response.get("data", {}).get("devices") or []
        vehicle_devices = [
            device
            for device in devices
            if device.get("deviceType") == "ELECTRIC_VEHICLES"
        ]

        _LOGGER.debug(
            "Found %d vehicle devices for account %s",
            len(vehicle_devices),
            account_number,
        )
        return vehicle_devices



    async def fetch_flex_planned_dispatches(self, device_id: str):
        """Fetch planned dispatches for a SmartFlex device."""
        response = await self._execute_graphql(
            FLEX_PLANNED_DISPATCHES_QUERY,
            variables={"deviceId": device_id},
        )

        if not isinstance(response, dict):
            _LOGGER.error(
                "Invalid response fetching flex planned dispatches for %s: %s",
                device_id,
                response,
            )
            return None

        if errors := response.get("errors"):
            _LOGGER.error(
                "GraphQL errors fetching flex planned dispatches for %s: %s",
                device_id,
                errors,
            )
            return None

        dispatches = response.get("data", {}).get("flexPlannedDispatches") or []
        _LOGGER.debug(
            "Fetched %d flex planned dispatches for device %s",
            len(dispatches),
            device_id,
        )
        return dispatches

    async def _fetch_account_and_devices(self, account_number: str):
            """Fetch account and device data (legacy helper)."""
            _LOGGER.info(
                "Using _fetch_account_and_devices (deprecated - using comprehensive query)"
            )
            all_data = await self.fetch_all_data(account_number)
            if not all_data:
                return {"account": {}, "devices": []}
            return {
                "account": all_data.get("account", {}),
                "devices": all_data.get("devices", []),
            }

    async def fetch_gas_meter_readings(
            self,
            account_number: str,
            pdr: str,
            *,
            date_from: str | None = None,
            date_to: str | None = None,
            first: int | None = None,
            last: int | None = None,
        ) -> list[dict]:
            """Fetch gas meter readings for the specified PDR."""
            variables = {
                "accountNumber": account_number,
                "pdr": pdr,
                "dateFrom": date_from,
                "dateTo": date_to,
                "first": first,
                "last": last,
            }

            _LOGGER.debug(
                "Fetching gas meter readings for account %s, PDR %s (first=%s, last=%s, date_from=%s, date_to=%s)",
                account_number,
                pdr,
                first,
                last,
                date_from,
                date_to,
            )

            response = await self._execute_graphql(
                GAS_METER_READINGS_QUERY,
                variables=variables,
            )

            if not isinstance(response, dict):
                _LOGGER.error(
                    "Invalid response fetching gas meter readings for account %s, PDR %s: %s",
                    account_number,
                    pdr,
                    response,
                )
                return []

            if errors := response.get("errors"):
                _LOGGER.error(
                    "GraphQL errors in gas meter readings response: %s",
                    errors,
                )
                return []

            readings_data = response.get("data", {}).get("gasMeterReadings")
            if not readings_data:
                _LOGGER.debug(
                    "No gas meter readings returned for account %s, PDR %s",
                    account_number,
                    pdr,
                )
                return []

            edges = readings_data.get("edges") or []
            readings: list[dict] = []
            for edge in edges:
                node = (edge or {}).get("node") or {}
                if not node:
                    continue
                readings.append(
                    {
                        "readingDate": node.get("readingDate"),
                        "readingType": node.get("readingType"),
                        "readingSource": node.get("readingSource"),
                        "value": self.to_float_or_none(node.get("consumptionValue")),
                        "unit": "m3",
                        "raw": node,
                    }
                )

            if readings:
                latest = readings[0]
                _LOGGER.debug(
                    "Fetched gas meter reading: %s on %s (type: %s, source: %s)",
                    latest.get("value"),
                    latest.get("readingDate"),
                    latest.get("readingType"),
                    latest.get("readingSource"),
                )

            return readings

    async def fetch_electricity_measurements(
            self,
            property_id: str,
            pod: str,
            *,
            start_on: str | None = None,
            end_on: str | None = None,
            first: int | None = None,
            last: int | None = None,
        ) -> list[dict]:
            """Fetch electricity measurements for the given property/POD."""
            variables = {
                "propertyId": property_id,
                "pod": pod,
                "startOn": start_on,
                "endOn": end_on,
                "first": first,
                "last": last,
            }

            _LOGGER.debug(
                "Fetching electricity measurements for property %s, POD %s (first=%s, last=%s, start_on=%s, end_on=%s)",
                property_id,
                pod,
                first,
                last,
                start_on,
                end_on,
            )

            response = await self._execute_graphql(
                PROPERTY_ELECTRICITY_MEASUREMENTS_QUERY,
                variables=variables,
            )

            if not isinstance(response, dict):
                _LOGGER.error(
                    "Invalid response fetching electricity measurements for property %s: %s",
                    property_id,
                    response,
                )
                return []

            if errors := response.get("errors"):
                _LOGGER.error(
                    "GraphQL errors in electricity measurements response: %s",
                    errors,
                )
                return []

            property_data = response.get("data", {}).get("property") or {}
            measurements_data = property_data.get("measurements") or {}
            edges = measurements_data.get("edges") or []

            measurements: list[dict] = []
            for edge in edges:
                node = (edge or {}).get("node") or {}
                if not node:
                    continue
                unit = node.get("unit") or "kWh"
                if isinstance(unit, str) and unit.lower() == "kwh":
                    unit = "kWh"

                measurements.append(
                    {
                        "readAt": node.get("readAt"),
                        "value": self.to_float_or_none(node.get("value")),
                        "unit": unit,
                        "source": node.get("source"),
                        "raw": node,
                    }
                )

            if measurements:
                latest = measurements[-1] if last else measurements[0]
                _LOGGER.debug(
                    "Fetched electricity measurement: %s %s at %s (source: %s)",
                    latest.get("value"),
                    latest.get("unit"),
                    latest.get("readAt"),
                    latest.get("source"),
                )
            else:
                _LOGGER.debug(
                    "No electricity measurements found for property %s, POD %s",
                    property_id,
                    pod,
                )

            return measurements

    @staticmethod
    def format_time_to_hh_mm(time_str: str) -> str:
            """Normalise user-provided time values to HH:MM format."""
            try:
                if isinstance(time_str, (int, float)):
                    if 0 <= time_str <= 23:
                        return f"{int(time_str):02d}:00"
                    raise ValueError("Numeric hour values must be between 0 and 23")

                if isinstance(time_str, str):
                    stripped = time_str.strip()
                    if stripped.isdigit() and len(stripped) <= 2:
                        hour = int(stripped)
                        if 0 <= hour <= 23:
                            return f"{hour:02d}:00"
                        raise ValueError("Hour component must be between 0 and 23")

                    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
                        try:
                            dt = datetime.strptime(stripped, fmt)
                            return f"{dt.hour:02d}:{dt.minute:02d}"
                        except ValueError:
                            continue

                    raise ValueError(
                        f"Could not parse time: '{time_str}'. Please use HH:MM format (e.g. '05:00')"
                    )

                raise ValueError(
                    f"Unsupported time value type: {type(time_str).__name__}"
                )

            except Exception as exc:
                if isinstance(exc, ValueError):
                    raise
                raise ValueError(f"Error processing time '{time_str}': {exc!s}")
