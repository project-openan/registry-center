import os
from typing import Callable, Optional
from cryptography.hazmat.backends import default_backend
from cryptography import x509
from cryptography.x509.oid import ExtensionOID


class CertificateValidationError(Exception):
    pass


class CertificateNotFoundError(CertificateValidationError):
    pass


class CertificateFormatError(CertificateValidationError):
    pass


class SignatureCertificateManager:
    def __init__(self, cert_path: str, external_validator: Optional[Callable] = None):
        self.cert_path = cert_path
        self.external_validator = external_validator

    def check_certificate(self) -> bool:
        try:
            self._check_certificate_exists()
            cert = self._load_certificate()
            self._validate_certificate_format(cert)

            if self.external_validator:
                self._call_external_validator(cert)

            return True
        except CertificateValidationError:
            raise
        except Exception as e:
            raise CertificateValidationError(f"Certificate) validation failed: {e}")

    def _check_certificate_exists(self):
        if not os.path.exists(self.cert_path):
            raise CertificateNotFoundError(f"Certificate file not found: {self.cert_path}")

    def _load_certificate(self):
        try:
            with open(self.cert_path, 'rb') as f:
                cert_data = f.read()
            return x509.load_pem_x509_certificate(cert_data, default_backend())
        except Exception as e:
            raise CertificateFormatError(f"Failed to load certificate: {e}")

    def _validate_certificate_format(self, cert):
        try:
            public_key = cert.public_key()
            if public_key is None:
                raise CertificateFormatError("Certificate has no public key")
        except Exception as e:
            raise CertificateFormatError(f"Invalid certificate format: {e}")

    def _call_external_validator(self, cert):
        try:
            is_valid = self.external_validator(cert)
            if not is_valid:
                raise CertificateValidationError("External certificate validation failed")
        except Exception as e:
            raise CertificateValidationError(f"External validator error: {e}")
