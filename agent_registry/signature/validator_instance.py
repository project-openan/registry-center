from agent_registry.signature.agent_card_signature_validator import AgentCardSignatureValidator
from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.public_key_manager import PublicKeyManager


def get_agent_card_validator() -> AgentCardSignatureValidator:
    """获取AgentCard验证器单例"""
    from functools import lru_cache
    
    @lru_cache(maxsize=1)
    def _get_validator() -> AgentCardSignatureValidator:
        public_key_manager = PublicKeyManager()
        jwk_fetcher = JWKFetcher(public_key_manager)
        return AgentCardSignatureValidator(jwk_fetcher)
    
    return _get_validator()
