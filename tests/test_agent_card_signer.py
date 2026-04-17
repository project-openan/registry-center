import pytest
from unittest.mock import Mock, patch, MagicMock
from agent_registry.agent_registry.agent_card_signer import AgentCardSigner


def test_is_enabled_true():
    with patch('agent_registry.agent_registry.agent_card_signer.AgentCardSigner._load_credentials'):
        signer = AgentCardSigner(
            private_key_path="dummy_key.pem",
            password_path=None,
            jku_url="http://example.com/jwks.json",
            algorithm="RS256",
            sign_enabled=True
        )
        
        mock_private_key = MagicMock()
        mock_public_key = MagicMock()
        mock_numbers = MagicMock()
        mock_numbers.n = 1234567890123456789012345645678901234564567890123456789012345645678901234567890123456123456789012345612345612345612345612345612345612345612345612345612345612345612345
        mock_numbers.e = 65537
        mock_public_key.public_numbers.return_value = mock_numbers
        mock_private_key.public_key.return_value = mock_public_key
        
        mock_signature = b'test_signature_data_256_bytes'
        mock_private_key.sign.return_value = mock_signature
        
        signer._private_key = mock_private_key
        
        mock_agent_card = MagicMock()
        mock_agent_card.model_dump.return_value = {
            "name": "test_agent",
            "version": "1.0.0"
        }
        mock_agent_copy = MagicMock()
        mock_agent_copy.signatures = []
        mock_agent_card.model_copy.return_value = mock_agent_copy
        
        result = signer.sign_agent_card(mock_agent_card)
        
        assert hasattr(result, 'signatures')
        assert len(result.signatures) == 1
        assert 'protected' in result.signatures[0]
        assert 'signature' in result.signatures[0]
        assert result.signatures[0]['protected']['alg'] == 'RS256'
        assert result.signatures[0]['protected']['use'] == 'sig'


def test_is_enabled_false():
    signer = AgentCardSigner(
        private_key_path="dummy_key.pem",
        password_path=None,
        jku_url=None,
        algorithm="RS256",
        sign_enabled=False
    )
    
    mock_agent_card = MagicMock()
    mock_agent_card_dict = {
        "name": "test_agent",
        "version": "1.0.0"
    }
    mock_agent_card.model_dump.return_value = mock_agent_card_dict
    
    result = signer.sign_agent_card(mock_agent_card)
    
    assert result == mock_agent_card_dict
    assert 'signatures' not in result


def test_is_enabled_method():
    signer_enabled = AgentCardSigner(
        private_key_path="dummy_key.pem",
        password_path=None,
        jku_url=None,
        algorithm="RS256",
        sign_enabled=True
    )
    
    signer_disabled = AgentCardSigner(
        private_key_path="dummy_key.pem",
        password_path=None,
        jku_url=None,
        algorithm="RS256",
        sign_enabled=False
    )
    
    assert signer_enabled.is_enabled() is True
    assert signer_disabled.is_enabled() is False
