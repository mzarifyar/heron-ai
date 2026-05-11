"""Secret Service client for retrieving secrets from a Vault-compatible endpoint."""
import base64
import os
import time
import warnings
from typing import Dict, Any, Optional
from utils.logger import log
from utils.settings import get_settings

# Silence the deprecation warning emitted by aws.base_client's datetime.utcnow usage.
warnings.filterwarnings(
    "ignore",
    message=r".*datetime\.datetime\.utcnow\(\) is deprecated.*",
    category=DeprecationWarning,
)

try:
    import aws
    import vaultpythonsdk
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False


class SSv2Client:
    """Provides SSv2Client behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self, service_endpoint: str, ca_bundle_path: str, secret_prefix: str):
        """Initializes instance state using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not AWS_AVAILABLE:
            raise RuntimeError("AWS SDK and vaultpythonsdk are required for secret service access")

        self.service_endpoint = service_endpoint
        self.ca_bundle_path = ca_bundle_path
        self.secret_prefix = secret_prefix

        # Initialize vault client with signer
        self.vault_client = vaultpythonsdk.vault_client.VaultClient(
            signer_provider=self,
            service_endpoint=service_endpoint,
            ca_bundle_path=ca_bundle_path
        )

        # Initialize secret cache
        self._secret_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_seconds = 3600  # 1 hour TTL

    @property
    def _aws_config(self) -> Dict[str, Any]:
        """Builds aws config using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not AWS_AVAILABLE:
            return {"region": "us-ashburn-1"}
        try:
            return aws.config.from_file()
        except Exception:
            # Get region from settings if available
            settings = get_settings()
            region = settings.get("telemetry", {}).get("region", "us-ashburn-1")
            return {"region": region}

    @property
    def _signer(self):
        """Builds signer using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not AWS_AVAILABLE:
            return None
        try:
            # Prefer local user config; fall back to instance/resource principals
            aws_config = self._aws_config
            token_file = aws_config.get("security_token_file")
            key_file = aws_config.get("key_file")
            if token_file and key_file:
                token = open(token_file, "r").read()
                private_key = aws.signer.load_private_key_from_file(key_file)
                return aws.auth.signers.SecurityTokenSigner(token, private_key)
        except Exception:
            pass
        try:
            return aws.auth.signers.InstancePrincipalsSecurityTokenSigner()
        except Exception:
            return None

    def get(self):
        """Gets the request using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return self._signer

    def get_base64_secret(self, secret_path: str) -> str:
        """Gets base64 secret using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        if not secret_path.startswith("/secret/"):
            secret_path = f"{self.secret_prefix}{secret_path}"
        if not secret_path.endswith("/latest"):
            secret_path = f"{secret_path}/latest"
        secret_details = self.vault_client.get_secret(path=secret_path)
        return secret_details.data.data["secret"]

    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Checks cache valid using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        return time.time() - cache_entry["timestamp"] < self._cache_ttl_seconds

    def get_plain_secret(self, secret_path: str) -> str:
        # Check cache first
        """Gets plain secret using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        if secret_path in self._secret_cache:
            cache_entry = self._secret_cache[secret_path]
            if self._is_cache_valid(cache_entry):
                # Decode from base64 cache
                log("debug", "Retrieved secret from cache: {}", secret_path)
                return base64.b64decode(cache_entry["value"]).decode("utf-8")

        # Cache miss or expired - fetch from service
        log("debug", "Fetching secret from secret service: {}", secret_path)
        base64_secret = self.get_base64_secret(secret_path)
        plain_secret = base64.b64decode(base64_secret).decode("utf-8")

        # Cache the base64-encoded result (not plaintext)
        self._secret_cache[secret_path] = {
            "value": base64_secret,  # Store base64, not plaintext
            "timestamp": time.time()
        }

        return plain_secret


# Global client instance
_secret_client: Optional[SSv2Client] = None


def get_secret_client() -> SSv2Client:
    """Gets secret client using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    global _secret_client
    if _secret_client is not None:
        return _secret_client

    # Required environment variables
    required_vars = [
        "SECRET_PATH_PREFIX",
        "SECRET_SERVICE_DOMAIN",
        "REQUESTS_CA_BUNDLE"
    ]

    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        raise RuntimeError(f"Missing required environment variables for secret service: {', '.join(missing_vars)}")

    # SERVICE_ENDPOINT may be set directly; otherwise construct from region + domain
    service_endpoint = os.environ.get("SECRET_SERVICE_ENDPOINT")
    if not service_endpoint:
        settings = get_settings()
        region = settings.get("telemetry", {}).get("region", "us-east-1")
        service_endpoint = f"https://secret-service.{region}.{os.environ['SECRET_SERVICE_DOMAIN']}/v1"

    _secret_client = SSv2Client(
        service_endpoint=service_endpoint,
        ca_bundle_path=os.environ["REQUESTS_CA_BUNDLE"],
        secret_prefix=os.environ["SECRET_PATH_PREFIX"]
    )

    return _secret_client