# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes

from common.cert.cert_exception import CertParseException
from common.cert.x509_obj import X509Obj, CertObj
from common.cert.cert_cn_parser import extract_cn_from_subject


SM2_SIGN = '1.2.156.10197.1.501'


def parse_cer_certificate(cert_path: str) -> X509Obj:
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()

        if b"-----BEGIN " not in cert_data:
            # DER binary mode, reading private keys not supported
            raise CertParseException(f'Parse certificate error! "-----BEGIN" not found! Unsupported der binary type! ')
        # Attempt to parse as certificate
        cert_org_list = x509.load_pem_x509_certificates(cert_data)
        cer_obj_list = _extract_certificate_infos(cert_org_list)
        # Trust certificates (cer) only contain certificates and public keys
        if len(cer_obj_list) == 0:
            raise CertParseException(f"Parse certificate error! No certificate found! ")
        # Multiple public keys
        x509_obj = X509Obj(cert_list=cer_obj_list)
        return x509_obj
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # Filter original parse exception info to prevent sensitive data leakage
            exception = CertParseException("Parse certificate error! ")
        raise exception


def parse_pem_files(cert_path: str, password: bytes = None) -> PrivateKeyTypes:
    try:
        with open(cert_path, 'rb') as f:
            p12_data = f.read()

        # Parse private key file using cryptography
        password_bytes = password
        private_key = serialization.load_pem_private_key(
            p12_data,
            password=password_bytes
        )

        # Process certificate
        if not private_key:
            raise CertParseException(f"Parse private key error! ")
        return private_key
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # Filter original parse exception info to prevent sensitive data leakage
            exception = CertParseException("Parse private key error! ")
        raise exception


def _extract_certificate_infos(cert_list: list[x509.Certificate]) -> list[CertObj]:
    result = []
    for cert in cert_list:
        result.append(_extract_certificate_info(cert))
    return result


def _extract_certificate_info(cert: x509.Certificate) -> CertObj:
    """Extract information from a cryptography certificate object"""
    # SM2 national cipher mode not supported
    if SM2_SIGN in cert.signature_algorithm_oid.dotted_string:
        raise CertParseException(f"Unsupported sm2 public key type: {SM2_SIGN}")
    subject_str = cert.subject.rfc4514_string()
    info = {
        'subject': subject_str,
        'issuer': cert.issuer.rfc4514_string(),
        'serial_number': hex(cert.serial_number),
        'valid_from': cert.not_valid_before_utc.isoformat(),
        'valid_to': cert.not_valid_after_utc.isoformat(),
        'version': cert.version,
        'public_key': cert.public_key(),
        'org_cert': cert,
        'cn': extract_cn_from_subject(subject_str)
    }
    obj = CertObj.from_dict(info)
    return obj


def parse_crl_list(cert_path: str) -> x509.CertificateRevocationList:
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()

        if b"-----BEGIN " not in cert_data:
            # DER binary mode, reading DER format CRLs not supported
            raise CertParseException(f'Parse crl file error! "-----BEGIN" not found! Unsupported der binary type! ')
        # Attempt to parse PEM format CRL
        crl_list = x509.load_pem_x509_crl(cert_data)
        if len(crl_list) == 0:
            raise CertParseException(f"Parse crl file error! No crl found! ")
        return crl_list
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # Filter original parse exception info to prevent sensitive data leakage
            exception = CertParseException("Parse crl file error! ")
        raise exception
