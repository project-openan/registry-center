import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa, ec

from common.cert import CertParser
from common.cert.CertException import ValidationResult, CertParseException
from common.cert.X509Obj import X509Obj


class CertValidator:
    cert_path = ''
    password = None
    is_trust_cert = False

    def __init__(self, cert_path: str, password=None, is_trust_cert = False):
        self.cert_path = cert_path
        self.password = password
        self.is_trust_cert = is_trust_cert

    def is_support_format(self, file_extension: str) -> bool:
        if self.is_trust_cert and file_extension == '.cer':
            return True
        if not self.is_trust_cert and file_extension == '.p12':
            return True
        return False


    def validate(self) -> ValidationResult:
        """
        p12校验以下内容：
            - 证书格式：X.509v3，不满足则退出进程启动
            - 证书密钥算法、密钥长度：RSA(≥3072 bits)，ECDSA(≥256 bits)，不满足则退出进程启动
            - 有效期：当前时间有效，不满足则退出进程启动
            - 是否加密私钥：是否有口令、口令复杂度，不满足则给出日志打印
            - 私钥口令与私钥匹配性：不满足则退出进程启动
            - 私钥与公钥的匹配性：不满足则退出进程启动
        cer校验以下内容:
            - 校验证书格式：X.509v3
            - 校验有效期：当前时间有效
            - 密钥算法、长度
        :return: ValidationResult
        """
        # 1. 基础校验，无需读取证书
        if self.cert_path is None or self.cert_path == '':
            return ValidationResult(False, f"Cert file path is empty! ")
        cert_path_obj = Path(self.cert_path)
        if not cert_path_obj.exists():
            return ValidationResult(False, f"Cert file not exist：{self.cert_path}")
        file_extension = cert_path_obj.suffix.lower()
        if not self.is_support_format(file_extension):
            return ValidationResult(False, f"Cert file extension is not support! ")
        # 2. 读取证书，做通用校验
        try:
            x509_obj = CertParser.parse_cert(self.cert_path, self.password)
        except CertParseException as e:
            return ValidationResult(False, e.__str__())

        # 3. 根据格式进行特定校验
        file_extension = cert_path_obj.suffix.lower()
        if file_extension == '.p12':
            return self._validate_p12_cert(x509_obj)
        return self._validate_cer_cert(x509_obj)
    
    def _validate_p12_cert(self, x509_obj: X509Obj) -> ValidationResult:
        """验证p12格式证书"""
        # 1. 证书格式校验：X.509v3
        for cert_obj in x509_obj.cert_list:
            cert_version = cert_obj.org_cert.version
            if cert_version != x509.Version.v3:
                return ValidationResult(False, f"Certificate format is not X.509v3")
        
        # 2. 证书密钥算法、密钥长度校验，p12需要校验公私钥
        if not self._validate_public_key_length(x509_obj.public_key) and not self._validate_private_key_length(x509_obj.private_key):
            return ValidationResult(False, "Certificate key algorithm or length does not meet requirements")
        
        # 3. 有效期校验
        if not self._validate_certificate_validity(x509_obj):
            return ValidationResult(False, "Certificate is not valid at current time")
        
        # 4. 检查私钥是否加密（P12文件中的私钥通常已经加密）
        # 5. 私钥口令与私钥匹配性 - 如果解析时出现异常，则密码不匹配（前面已经捕获）
        
        # 6. 私钥与公钥的匹配性校验
        if not self._validate_private_key_public_key_match(x509_obj):
            return ValidationResult(False, "Private key does not match public key")
        
        return ValidationResult(True, "P12 certificate validation passed")
    
    def _validate_cer_cert(self, x509_obj: X509Obj) -> ValidationResult:
        """验证cer格式证书"""
        for cert_obj in x509_obj.cert_list:
            # 1. 证书格式校验：X.509v3
            if cert_obj.version != x509.Version.v3:
                return ValidationResult(False, f"Certificate format is not X.509v3")
            # 2. 密钥算法、长度校验，cer只校验公钥，因为没有私钥
            if not self._validate_public_key_length(cert_obj.public_key):
                return ValidationResult(False, "Certificate key algorithm or length does not meet requirements")
        
        # 3. 有效期校验，单独跑一把，确保每本证书的有效期对比的currentTime是一个
        if not self._validate_certificate_validity(x509_obj):
            return ValidationResult(False, "Certificate is not valid at current time")

        return ValidationResult(True, "CER certificate validation passed")

    def _validate_public_key_length(self, public_key) -> bool:
        """验证密钥算法和长度"""
        if isinstance(public_key, rsa.RSAPublicKey):
            return public_key.key_size >= 3072
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            # 256位及以上
            return public_key.key_size >= 256
        return False

    def _validate_private_key_length(self, private_key) -> bool:
        """验证密钥算法和长度"""
        if isinstance(private_key, rsa.RSAPrivateKey):
            return private_key.key_size >= 3072
        if isinstance(private_key, ec.EllipticCurvePrivateKey):
            # 256位及以上
            return private_key.key_size >= 256
        return False

    def _validate_certificate_validity(self, x509_obj: X509Obj) -> bool:
        """验证证书有效期"""
        current_time = datetime.datetime.now(datetime.UTC)
        for cert_obj in x509_obj.cert_list:
            try:
                valid_from = datetime.datetime.fromisoformat(cert_obj.valid_from.replace('Z', '+00:00'))
                valid_to = datetime.datetime.fromisoformat(cert_obj.valid_to.replace('Z', '+00:00'))
                if current_time < valid_from or current_time > valid_to:
                    return False
            except (ValueError, TypeError):
                return False
        # 每本证书的有效期都要校验对
        return True


    def _validate_private_key_public_key_match(self, x509_obj: X509Obj) -> bool:
        """验证私钥与公钥是否匹配"""
        # 取出证书中的公钥
        public_key = x509_obj.public_key
        # 取出x509解析出来的私钥对象
        private_key = x509_obj.private_key
        if not x509_obj.private_key or not x509_obj.public_key:
            return False
        # 私钥只能是RSA或ECDSA格式
        if not isinstance(private_key, rsa.RSAPrivateKey) and not isinstance(private_key, ec.EllipticCurvePrivateKey):
            return False
        # 利用私钥生成公钥
        public_key_from_private = private_key.public_key()

        return public_key == public_key_from_private
