from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes

from common.cert.cert_exception import CertParseException
from common.cert.x509_obj import X509Obj, CertObj


SM2_SIGN = '1.2.156.10197.1.501'


def parse_cer_certificate(cert_path: str) -> X509Obj:
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()

        if b"-----BEGIN " not in cert_data:
            # der二进制模式，不支持读取私钥
            raise CertParseException(f'Parse certificate error! "-----BEGIN" not found! Unsupported der binary type! ')
        # 尝试解析为证书
        cert_org_list = x509.load_pem_x509_certificates(cert_data)
        cer_obj_list = _extract_certificate_infos(cert_org_list)
        # cer对应的是信任证书，仅包含证书和公钥
        if len(cer_obj_list) == 0:
            raise CertParseException(f"Parse certificate error! No certificate found! ")
        # 有多个公钥
        x509_obj = X509Obj(cert_list=cer_obj_list)
        return x509_obj
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # 过滤原始解析异常信息，防止敏感信息泄漏
            exception = CertParseException("Parse certificate error! ")
        raise exception


def parse_pem_files(cert_path: str, password: bytes = None) -> PrivateKeyTypes:
    try:
        with open(cert_path, 'rb') as f:
            p12_data = f.read()

        # 使用cryptography解析私钥文件
        password_bytes = password
        private_key = serialization.load_pem_private_key(
            p12_data,
            password=password_bytes
        )

        # 处理证书
        if not private_key:
            raise CertParseException(f"Parse private key error! ")
        return private_key
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # 过滤原始解析异常信息，防止敏感信息泄漏
            exception = CertParseException("Parse private key error! ")
        raise exception


def _extract_certificate_infos(cert_list: list[x509.Certificate]) -> list[CertObj]:
    result = []
    for cert in cert_list:
        result.append(_extract_certificate_info(cert))
    return result


def _extract_certificate_info(cert: x509.Certificate) -> CertObj:
    """从cryptography证书对象中提取信息"""
    # 国密模式不支持
    if SM2_SIGN in cert.signature_algorithm_oid.dotted_string:
        raise CertParseException(f"Unsupported sm2 public key type: {SM2_SIGN}")
    info = {
        'subject': cert.subject.rfc4514_string(),
        'issuer': cert.issuer.rfc4514_string(),
        'serial_number': hex(cert.serial_number),
        'valid_from': cert.not_valid_before_utc.isoformat(),
        'valid_to': cert.not_valid_after_utc.isoformat(),
        'version': cert.version,
        'public_key': cert.public_key(),
        'org_cert': cert
    }
    obj = CertObj.from_dict(info)
    return obj


def parse_crl_list(cert_path: str) -> x509.CertificateRevocationList:
    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()

        if b"-----BEGIN " not in cert_data:
            # der二进制模式，不支持读取der格式的crl
            raise CertParseException(f'Parse crl file error! "-----BEGIN" not found! Unsupported der binary type! ')
        # 尝试解析PEM格式的CRL
        crl_list = x509.load_pem_x509_crl(cert_data)
        if len(crl_list) == 0:
            raise CertParseException(f"Parse crl file error! No crl found! ")
        return crl_list
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # 过滤原始解析异常信息，防止敏感信息泄漏
            exception = CertParseException("Parse crl file error! ")
        raise exception
