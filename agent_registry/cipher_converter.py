from loguru import logger


class CipherConverter:
    """IANA格式到OpenSSL格式的转换器"""

    # IANA到OpenSSL的完整映射表
    IANA_TO_OPENSSL = {
        # TLS 1.3 套件（保持原样）
        'TLS_AES_256_GCM_SHA384': 'TLS_AES_256_GCM_SHA384',
        'TLS_AES_128_GCM_SHA256': 'TLS_AES_128_GCM_SHA256',
        'TLS_CHACHA20_POLY1305_SHA256': 'TLS_CHACHA20_POLY1305_SHA256',

        # ECDHE-ECDSA 套件
        'TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384': 'ECDHE-ECDSA-AES256-GCM-SHA384',
        'TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256': 'ECDHE-ECDSA-AES128-GCM-SHA256',

        # ECDHE-RSA 套件
        'TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384': 'ECDHE-RSA-AES256-GCM-SHA384',
        'TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256': 'ECDHE-RSA-AES128-GCM-SHA256',

        # DHE-RSA 套件
        'TLS_DHE_RSA_WITH_AES_256_GCM_SHA384': 'DHE-RSA-AES256-GCM-SHA384',
        'TLS_DHE_RSA_WITH_AES_128_GCM_SHA256': 'DHE-RSA-AES128-GCM-SHA256',

        # DHE-DSS 套件
        'TLS_DHE_DSS_WITH_AES_256_GCM_SHA384': 'DHE-DSS-AES256-GCM-SHA384',
        'TLS_DHE_DSS_WITH_AES_128_GCM_SHA256': 'DHE-DSS-AES128-GCM-SHA256',
    }

    @classmethod
    def convert(cls, iana_cipher_string: str) -> str:
        """
        将IANA格式的密码套件字符串转换为OpenSSL格式
        输入: "TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256"
        输出: "TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256"
        """
        # 1. 分割字符串
        ciphers = [c.strip() for c in iana_cipher_string.split(',')]

        # 2. 转换每个密码套件
        openssl_ciphers = []
        for cipher in ciphers:
            if cipher in cls.IANA_TO_OPENSSL:
                openssl_ciphers.append(cls.IANA_TO_OPENSSL[cipher])
            else:
                # 尝试自动转换
                converted = cls._auto_convert(cipher)
                if converted:
                    openssl_ciphers.append(converted)
                    logger.info(f"警告: 自动转换 {cipher} -> {converted}")
                else:
                    logger.info(f"警告: 跳过无法识别的密码套件: {cipher}")

        # 3. 用冒号连接
        return ':'.join(openssl_ciphers)

    @classmethod
    def _auto_convert(cls, cipher: str) -> str:
        """自动转换未知格式的密码套件"""
        try:
            # 移除 TLS_ 前缀
            if cipher.startswith('TLS_'):
                cipher = cipher[4:]

            # 替换 _WITH_ 为 -
            cipher = cipher.replace('_WITH_', '-')

            # 替换其他下划线为连字符
            cipher = cipher.replace('_', '-')

            return cipher
        except Exception as e:
            logger.error(f"Convert Cipher Failed: {e}")
            return ""
