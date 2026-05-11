from typing import List, Dict, Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography import x509
from jwt.api_jwk import PyJWK


class CertLoadError(Exception):
    pass


class JWKProvider:
    def __init__(self, cert_path: str):
        self.cert_path = cert_path
        self._jwk_set = None

    def get_jwk_set(self) -> List[PyJWK]:
        if self._jwk_set is None:
            self._jwk_set = self._load_jwk_set()
        return self._jwk_set

    def get_public_key_pem(self) -> bytes:
        try:
            with open(self.cert_path, 'rb') as f:
                cert_data = f.read()

            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            public_key = cert.public_key()

            public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            return public_key_pem
        except Exception as e:
            raise CertLoadError(f"Failed to load public key: {e}")

    def _load_jwk_set(self) -> List[PyJWK]:
        try:
            with open(self.cert_path, 'rb') as f:
                cert_data = f.read()

            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            public_key = cert.public_key()

            jwk_dict = self._public_key_to_jwk_dict(public_key)
            jwk = PyJWK(jwk_dict)

            return [jwk]
        except Exception as e:
            raise CertLoadError(f"Failed to load certificate: {e}")

    def _public_key_to_jwk_dict(self, public_key) -> Dict[str, Any]:
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        if public_key.__class__.__name__ == 'RSAPublicKey':
            return self._rsa_to_jwk_dict(public_key)
        elif public_key.__class__.__name__ == 'EllipticCurvePublicKey':
            return self._ec_to_jwk_dict(public_key)
        else:
            raise CertLoadError(f"Unsupported key type: {public_key.__class__.__name__}")

    def _rsa_to_jwk_dict(self, public_key) -> Dict[str, Any]:
        from cryptography.hazmat.primitives.asymmetric import rsa

        if not isinstance(public_key, rsa.RSAPublicKey):
            raise CertLoadError("Expected RSA public key")

        numbers = public_key.public_numbers()

        return {
            "kty": "RSA",
            "n": self._base64url_encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, 'big')),
            "e": self._base64url_encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, 'big')),
            "alg": "RS256",
            "use": "sig"
        }

    def _ec_to_jwk_dict(self, public_key) -> Dict[str, Any]:
        from cryptography.hazmat.primitives.asymmetric import ec

        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise CertLoadError("Expected EC public key")

        numbers = public_key.public_numbers()
        curve_name = public_key.curve.name

        curve_map = {
            'secp256r1': 'P-256',
            'secp384r1': 'P-384',
            'secp521r1': 'P-521'
        }

        if curve_name not in curve_map:
            raise CertLoadError(f"Unsupported curve: {curve_name}")

        coord_bytes = (numbers.x.bit_length() + 7) // 8

        return {
            "kty": "EC",
            "crv": curve_map[curve_name],
            "x": self._base64url_encode(numbers.x.to_bytes(coord_bytes, 'big')),
            "y": self._base64url_encode(numbers.y.to_bytes(coord_bytes, 'big')),
            "alg": "ES256",
            "use": "sig"
        }

    def _base64url_encode(self, data: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')
