import json
import base64
from typing import Optional, List, Dict, Any
from loguru import logger

from common.util.config_util import get_conf
from a2a.types import AgentCard
from a2a.utils.signing import create_signature_verifier, InvalidSignaturesError, NoSignatureError
from google.protobuf.json_format import MessageToDict

from agent_registry.signature.models import SignatureObject, ProtectedHeader
from agent_registry.signature.jwk_fetcher import JWKFetcher


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
    """AgentCard signature validator (supports protobuf AgentCard)"""

    def __init__(self, jwk_fetcher: JWKFetcher):
        self.jwk_fetcher = jwk_fetcher
        self._signature_validation_enabled = self._load_signature_config()

    @staticmethod
    def _load_signature_config() -> bool:
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
            return True

    def validate_agent_card(
        self,
        agent_card: AgentCard
    ) -> ValidationResult:
        """
        Validate AgentCard signature.

        Args:
            agent_card: protobuf AgentCard object.

        Returns:
            ValidationResult: Validation result.
        """
        try:
            if not self._signature_validation_enabled:
                logger.info("Signature validation is disabled, skipping validation")
                return ValidationResult(is_valid=True)

            organization = agent_card.provider.organization
            agent_name = agent_card.name
            provider_url = agent_card.provider.url

            signatures = self._extract_signatures_from_protobuf(agent_card)
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

            for sig_obj in signatures:
                protected_header = self._decode_protected(sig_obj.protected)
                if not protected_header:
                    logger.warning(f"Failed to decode protected header: {sig_obj.protected}")
                    continue

                kid = protected_header.kid

                backend_key_fetcher = self.jwk_fetcher.create_backend_key_fetcher(organization, agent_name, provider_url)
                backend_key = backend_key_fetcher(kid, "")

                if backend_key:
                    logger.info(f"Using backend key for kid: {kid}")
                    verifier = create_signature_verifier(backend_key_fetcher, ['ES256', 'RS256'])
                    try:
                        verifier(agent_card)
                        logger.info(f"Signature validation passed with backend key: {kid}")
                        return ValidationResult(is_valid=True)
                    except (NoSignatureError, InvalidSignaturesError) as e:
                        logger.warning(f"Backend key signature validation failed: {e}")
                    except TypeError as e:
                        logger.warning(f"Backend key fetcher returned None: {e}")
                    except Exception as e:
                        logger.warning(f"Unexpected backend signature validation error: {e}")

            logger.info("Trying jku key signature.")
            jku_key_fetcher = lambda key_id, jku: self.jwk_fetcher.fetch_jku_key(key_id, jku)
            verifier = create_signature_verifier(jku_key_fetcher, ['ES256', 'RS256'])
            try:
                verifier(agent_card)
                logger.info("Signature validation passed with jku key.")
                return ValidationResult(is_valid=True)
            except NoSignatureError as e:
                logger.error(f"No valid signature found: {e}")
            except InvalidSignaturesError as e:
                logger.error(f"JKU signature validation failed: {e}")
            except TypeError as e:
                logger.error(f"Failed to fetch signature key from JKU URL: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during JKU signature validation: {e}")

            logger.error("All signature validations failed")
            return ValidationResult(
                is_valid=False,
                error_code="SIG005",
                error_message="Signature validation failed: unable to verify signature with provided keys. Please ensure backend public key is configured or JKU URL is accessible.",
                details={
                    "total_signatures": len(signatures),
                    "backend_key_checked": True,
                    "jku_key_checked": True
                }
            )

        except Exception as e:
            logger.error(f"Signature validation internal error: {e}")
            return ValidationResult(
                is_valid=False,
                error_code="SIG999",
                error_message=f"Signature validation internal error: {str(e)}",
                details={"error": str(e)}
            )

    @staticmethod
    def _extract_signatures_from_protobuf(agent_card: AgentCard) -> List[SignatureObject]:
        """Extract signatures from protobuf AgentCard"""
        try:
            signatures = agent_card.signatures
            if not signatures:
                return []

            signature_objects = []
            for sig in signatures:
                protected = sig.protected
                signature = sig.signature
                
                if not protected or not signature:
                    logger.warning("Missing required fields in signature")
                    continue

                sig_dict = {
                    "protected": protected,
                    "signature": signature
                }
                if sig.header:
                    sig_dict["header"] = MessageToDict(sig.header)
                
                signature_objects.append(SignatureObject(**sig_dict))

            return signature_objects

        except Exception as e:
            logger.error(f"Failed to extract signatures: {e}")
            return []

    @staticmethod
    def _decode_protected(protected: str) -> Optional[ProtectedHeader]:
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