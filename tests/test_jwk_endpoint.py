import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from agent_registry.agent_registry.jwk_provider import JWKProvider, CertLoadError
from jwt.api_jwk import PyJWK


@pytest.fixture(scope="module")
def mock_jwk_provider():
    with patch('agent_registry.agent_registry.jwk_provider.JWKProvider') as mock_class:
        provider_instance = Mock()
        
        jwk_mock = MagicMock(spec=PyJWK)
        jwk_mock._jwk_data = {
            "kty": "RSA",
            "n": "test_n_value",
            "e": "test_e_value",
            "alg": "RS256",
            "use": "sig"
        }
        
        provider_instance.get_jwk_set.return_value = [jwk_mock]
        mock_class.return_value = provider_instance
        yield provider_instance


@pytest.fixture
def client(mock_jwk_provider):
    from agent_registry.agent_registry import server
    return TestClient(server.app)


def test_get_jwks_success(client):
    response = client.get("/rest/v1/registry-center/keys")
    assert response.status_code == 200
    
    data = response.json()
    assert "keys" in data
    assert len(data["keys"]) == 1
    
    jwk = data["keys"][0]
    assert jwk["kty"] == "RSA"
    assert jwk["n"] == "test_n_value"
    assert jwk["e"] == "test_e_value"
    assert jwk["alg"] == "RS256"
    assert jwk["use"] == "sig"
    assert jwk["key_ops"] == ["verify"]


def test_get_jwks_rate_limit_exceeded(client):
    for i in range(10):
        response = client.get("/rest/v1/registry-center/keys")
        assert response.status_code == 200
    
    for i in range(5):
        response = client.get("/rest/v1/registry-center/keys")
        assert response.status_code == 429
        assert "Too Many Requests" in response.json()["detail"]


def test_get_jwks_internal_error():
    with patch('agent_registry.agent_registry.jwk_provider.JWKProvider') as mock_class:
        provider_instance = Mock()
        provider_instance.get_jwk_set.side_effect = CertLoadError("Failed to load certificate")
        mock_class.return_value = provider_instance
        
        from agent_registry.agent_registry import server
        test_client = TestClient(server.app)
        
        with patch('loguru.logger.error') as mock_logger:
            response = test_client.get("/rest/v1/registry-center/keys")
            assert response.status_code == 500
            assert "Failed to load certificate" in response.json()["detail"]
            mock_logger.assert_called()
