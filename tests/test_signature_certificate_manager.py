import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from agent_registry.agent_registry.signature_certificate_manager import (
    SignatureCertificateManager,
    CertificateNotFoundError,
    CertificateFormatError,
    CertificateValidationError
)


def test_certificate_not_found():
    non_existent_path = "non_existent_cert.pem"
    manager = SignatureCertificateManager(cert_path=non_existent_path)
    
    with pytest.raises(CertificateNotFoundError) as exc_info:
        manager.check_certificate()
    
    assert "Certificate file not found" in str(exc_info.value)
    assert non_existent_path in str(exc_info.value)


def test_certificate_invalid_format():
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pem') as temp_file:
        temp_file.write("This is not a valid certificate")
        temp_file_path = temp_file.name
    
    try:
        manager = SignatureCertificateManager(cert_path=temp_file_path)
        
        with pytest.raises(CertificateFormatError) as exc_info:
            manager.check_certificate()
        
        assert "Failed to load certificate" in str(exc_info.value)
    finally:
        os.unlink(temp_file_path)


def test_certificate_valid():
    with patch('agent_registry.agent_registry.signature_certificate_manager.x509.load_pem_x509_certificate') as mock_load:
        mock_cert = MagicMock()
        mock_public_key = MagicMock()
        mock_cert.public_key.return_value = mock_public_key
        mock_load.return_value = mock_cert
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pem') as temp_file:
            temp_file.write("-----BEGIN CERTIFICATE-----\nMOCK CERT DATA\n-----END CERTIFICATE-----")
            temp_file_path = temp_file.name
        
        try:
            manager = SignatureCertificateManager(cert_path=temp_file_path)
            result = manager.check_certificate()
            assert result is True
        finally:
            os.unlink(temp_file_path)
