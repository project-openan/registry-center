import json
import base64
from typing import Optional, List, Dict, Any
from loguru import logger

from common.util.config_util import get_conf
from a2a.utils.signing import create_signature_verifier, InvalidSignaturesError, NoSignatureError

from agent_registry.signature.models import SignatureObject, ProtectedHeader
from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.model.validated_agentcard import ValidatedAgentCard


class ValidationResult:
    """Validation result"""
    def __init__(
        self,
        is_valid: bool,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.is_valid = is_valid
        self.error_code = error_code
        self.error_message = error_message
        self.details = details or {}


class AgentCardSignatureValidator:
    """AgentCard signature validator"""

    def __init__(self, jwk_fetcher: JWKFetcher):
        self.jwk_fetcher = jwk_fetcher
        self._signature_validation_enabled = self._load_signature_config()

    def _load_signature_config(self) -> bool:
        """
        Load signature validation toggle from configuration file.

        Returns:
            bool: Whether signature validation is enabled.
        """
        try:
            config = get_conf()
            enabled = config.get('signature_validation_enabled', 'true')
            return enabled.lower() == 'true'
        except Exception as e:
            logger.error(f"Failed to load signature validation config: {e}")
            return True  # Validation enabled by default

    def validate_agent_card(
        self,
        agent_card: ValidatedAgentCard
    ) -> ValidationResult:
        """
        Validate AgentCard signature.

        Args:
            agent_card: ValidatedAgentCard object.

        Returns:
            ValidationResult: Validation result.
        """
        try:
            # Check if signature validation is enabled
            if not self._signature_validation_enabled:
                logger.info("Signature validation is disabled, skipping validation")
                return ValidationResult(is_valid=True)

            organization = agent_card.provider.organization
            agent_name = agent_card.name
            provider_url = agent_card.provider.url

            agent_card_data = agent_card.model_dump()
            signatures = self._extract_signatures(agent_card_data)
            if not signatures:
                return ValidationResult(
                    is_valid=False,
                    error_code="SIG001",
                    error_message="Signatures field is required when signature validation is enabled",
                    details={
                        "validation_enabled": True,
                        "signatures_found": False
                    }
                )

            # Step 1: Iterate over the signatures array
            for sig_obj in signatures:
                protected_header = self._decode_protected(sig_obj.protected)
                if not protected_header:
                    logger.warning(f"Failed to decode protected header: {sig_obj.protected}")
                    continue

                kid = protected_header.kid

                backend_key_fetcher = self.jwk_fetcher.create_backend_key_fetcher(organization, agent_name, provider_url)
                backend_key = backend_key_fetcher(kid, "")  # jku not needed for backend keys, use empty string

                # Step 2: Try to get public key from backend and verify
                if backend_key:
                    logger.info(f"Using backend key for kid: {kid}")
                    verifier = create_signature_verifier(backend_key_fetcher, ['ES256', 'RS256'])
                    try:
                        verifier(agent_card)
                        logger.info(f"Signature validation passed with backend key: {kid}")
                        return ValidationResult(is_valid=True)
                    except (NoSignatureError, InvalidSignaturesError) as e:
                        logger.warning(f"Backend key validation failed: {e}")

            # Step 3: Try to get public key from jku and verify
            logger.info(f"Trying jku key signature.")
            jku_key_fetcher = lambda key_id, jku: self.jwk_fetcher.fetch_jku_key(key_id, jku)
            verifier = create_signature_verifier(jku_key_fetcher, ['ES256', 'RS256'])
            try:
                verifier(agent_card)
                logger.info(f"Signature validation passed with jku key.")
                return ValidationResult(is_valid=True)
            except NoSignatureError:
                logger.error("No jku key found.")
            except InvalidSignaturesError:
                logger.error("Jku key signature validations failed")

            # Both verification methods failed; report failure
            logger.error("All signature validations failed")
            return ValidationResult(
                is_valid=False,
                error_code="SIG005",
                error_message="All signature validations failed",
                details={
                    "total_signatures": len(signatures)
                }
            )

        except Exception as e:
            logger.error(f"AgentCard validation error: {e}")
            return ValidationResult(
                is_valid=False,
                error_code="SIG999",
                error_message="Internal server error",
                details={"error": str(e)}
            )

    def _extract_signatures(self, agent_card_data: dict) -> List[SignatureObject]:
        """Extract signatures field"""
        try:
            signatures = agent_card_data.get("signatures")
            if not signatures:
                return []

            signature_objects = []
            for sig in signatures:
                if not isinstance(sig, dict):
                    logger.warning(f"Invalid signature format: {sig}")
                    continue

                if "protected" not in sig or "signature" not in sig:
                    logger.warning("Missing required fields in signature")
                    continue

                signature_objects.append(SignatureObject(**sig))

            return signature_objects

        except Exception as e:
            logger.error(f"Failed to extract signatures: {e}")
            return []

    def _decode_protected(self, protected: str) -> Optional[ProtectedHeader]:
        """Decode protected header"""
        try:
            padding = 4 - len(protected) % 4
            if padding != 4:
                protected += '=' * padding
            decoded_bytes = base64.urlsafe_b64decode(protected)

            protected_json = decoded_bytes.decode('utf-8')
            protected_dict = json.loads(protected_json)

            return ProtectedHeader(**protected_dict)

        except Exception as e:
            logger.error(f"Failed to decode protected header: {e}")
            return None
