from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12

from common.cert.CertException import CertParseException
from common.cert.X509Obj import X509Obj, CertObj

SM2_SIGN = '1.2.156.10197.1.501'


def parse_cert(cert_path: str, password: str = None) -> X509Obj:
    cert_path_obj = Path(cert_path)
    if not cert_path_obj.exists():
        raise CertParseException(f"Cert file not exist：{cert_path}")

    file_extension = cert_path_obj.suffix.lower()
    x509_obj = None
    if file_extension == '.cer':
        # 可以解析出来多本
        x509_obj = parse_cer_certificate(cert_path)
    elif file_extension == '.p12':
        # 只能解析出来一本
        x509_obj = parse_p12_certificate(cert_path, password)
    else:
        raise CertParseException(f"Unsupported cert type: {file_extension}")
    if len(x509_obj.cert_list) == 0:
        raise CertParseException(f"No certificate found! ")
    return x509_obj


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
        # 有多个公钥的话，取1个就够了
        x509_obj = X509Obj(cert_list=cer_obj_list)
        return x509_obj
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # 过滤原始解析异常信息，防止敏感信息泄漏
            exception = CertParseException("Parse certificate error! ")
        raise exception


def parse_p12_certificate(cert_path: str, password: str = None) -> X509Obj:
    try:
        with open(cert_path, 'rb') as f:
            p12_data = f.read()

        # 使用cryptography解析PKCS#12文件
        password_bytes = password.encode() if password else None
        # p12里面只有1本证书
        privatekey, certificate, additional_certs = pkcs12.load_key_and_certificates(
            p12_data, password=password_bytes)

        # 处理证书
        if not certificate or not privatekey:
            raise CertParseException(f"Parse certificate or private key error! ")

        cert_obj = _extract_certificate_info(certificate)
        x509_obj = X509Obj(cert_list=[cert_obj], private_key=privatekey, public_key=cert_obj.public_key)
        return x509_obj
    except Exception as e:
        exception = e
        if not isinstance(e, CertParseException):
            # 过滤原始解析异常信息，防止敏感信息泄漏
            exception = CertParseException("Parse certificate error! ")
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
        'signature_algorithm': cert.signature_algorithm_oid._name,
        'org_cert': cert
    }
    obj = CertObj.from_dict(info)
    return obj
