#!/usr/bin/env python3
import sys
import os

from common.cert.certificate_generator import CertificateGenerator
from common.util.password_util import input_password_with_validation


def generate_self_signed_cert(cert_dir: str, cert_usage: str, password: str) -> bool:
    """
    生成自签名证书（新接口）
    :param cert_dir: 证书目录路径
    :param cert_usage: 证书用途，serverAuth 或 dataSigning
    :param password: 私钥加密口令
    :return: 生成成功返回True，否则返回False
    """
    try:
        generator = CertificateGenerator(key_algorithm='RSA')
        success = generator.generate_self_signed_cert(cert_dir, cert_usage, password)

        if success:
            print(f"Successfully generated self-signed certificates in {cert_dir}")
            return True
        else:
            print(f"Failed to generate certificates")
            return False
    except Exception as e:
        print(f"Error generating certificates: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) != 3:
        print("Usage: python generate_selfsign_cert.py <cert_dir> <cert_usage>")
        print("  cert_dir: Certificate directory path")
        print("  cert_usage: Certificate usage (serverAuth or dataSigning)")
        sys.exit(1)

    cert_dir = sys.argv[1]
    cert_usage = sys.argv[2]

    if cert_usage not in ["serverAuth", "dataSigning"]:
        print("Error: cert_usage must be 'serverAuth' or 'dataSigning'")
        sys.exit(1)

    password = input_password_with_validation("Enter private key password")

    if generate_self_signed_cert(cert_dir, cert_usage, password):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
