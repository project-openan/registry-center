import os
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

from common.cert.certificate_generator import CertificateGenerator
from common.cert.cert_parser import parse_cer_certificate, parse_pem_files


class TestCertificateGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.generator = CertificateGenerator(key_algorithm='RSA')

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_check_certificates_exists_no_files(self):
        result = self.generator._check_certificates_exists(self.temp_dir)
        self.assertFalse(result)

    def test_check_certificates_exists_cert_file(self):
        cert_file = os.path.join(self.temp_dir, "server.cer")
        with open(cert_file, 'w') as f:
            f.write("test")
        result = self.generator._check_certificates_exists(self.temp_dir)
        self.assertTrue(result)

    def test_check_certificates_exists_key_file(self):
        key_file = os.path.join(self.temp_dir, "server_key.pem")
        with open(key_file, 'w') as f:
            f.write("test")
        result = self.generator._check_certificates_exists(self.temp_dir)
        self.assertTrue(result)

    def test_check_certificates_exists_pwd_file(self):
        pwd_file = os.path.join(self.temp_dir, "cert_pwd")
        with open(pwd_file, 'w') as f:
            f.write("test")
        result = self.generator._check_certificates_exists(self.temp_dir)
        self.assertTrue(result)

    def test_generate_key_rsa(self):
        private_key = self.generator._generate_key()
        self.assertIsNotNone(private_key)
        self.assertEqual(private_key.key_size, 3072)

    def test_generate_key_unsupported_algorithm(self):
        generator = CertificateGenerator(key_algorithm='ECDSA')
        with self.assertRaises(ValueError):
            generator._generate_key()

    def test_generate_certificates_success(self):
        cert_usage = ["serverAuth"]
        result = self.generator.generate_certificates(self.temp_dir, cert_usage)
        self.assertTrue(result)

        cert_file = os.path.join(self.temp_dir, "server.cer")
        key_file = os.path.join(self.temp_dir, "server_key.pem")
        pwd_file = os.path.join(self.temp_dir, "cert_pwd")

        self.assertTrue(os.path.exists(cert_file))
        self.assertTrue(os.path.exists(key_file))
        self.assertTrue(os.path.exists(pwd_file))

    def test_generate_certificates_already_exists(self):
        cert_file = os.path.join(self.temp_dir, "server.cer")
        with open(cert_file, 'w') as f:
            f.write("test")

        cert_usage = ["serverAuth"]
        result = self.generator.generate_certificates(self.temp_dir, cert_usage)
        self.assertFalse(result)

    def test_generate_certificates_creates_directory(self):
        new_dir = os.path.join(self.temp_dir, "new_cert_dir")
        self.assertFalse(os.path.exists(new_dir))

        cert_usage = ["serverAuth"]
        result = self.generator.generate_certificates(new_dir, cert_usage)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_dir))

    def test_save_server_cert(self):
        private_key = self.generator._generate_key()
        cert_usage = ["serverAuth"]
        self.generator._save_server_cert(self.temp_dir, private_key, cert_usage)

        cert_file = os.path.join(self.temp_dir, "server.cer")
        self.assertTrue(os.path.exists(cert_file))

        x509_obj = parse_cer_certificate(cert_file)
        self.assertIsNotNone(x509_obj)
        self.assertEqual(len(x509_obj.cert_list), 1)

        cert_obj = x509_obj.cert_list[0]
        self.assertIn("agent-registry", cert_obj.subject)
        self.assertIn("agent-registry", cert_obj.issuer)

    def test_save_encrypted_key(self):
        private_key = self.generator._generate_key()
        password = b"test_password_123"
        self.generator._save_encrypted_key(self.temp_dir, private_key, password)

        key_file = os.path.join(self.temp_dir, "server_key.pem")
        self.assertTrue(os.path.exists(key_file))

        with open(key_file, 'rb') as f:
            content = f.read()
            self.assertIn(b"-----BEGIN PRIVATE KEY-----", content)
            self.assertIn(b"-----END PRIVATE KEY-----", content)

    def test_save_encrypted_password(self):
        password = b"test_password_123"
        self.generator._save_encrypted_password(self.temp_dir, password)

        pwd_file = os.path.join(self.temp_dir, "cert_pwd")
        self.assertTrue(os.path.exists(pwd_file))

        with open(pwd_file, 'r') as f:
            content = f.read()
            self.assertEqual(content, "test_password_123")

    def test_set_file_permissions(self):
        cert_file = os.path.join(self.temp_dir, "server.cer")
        key_file = os.path.join(self.temp_dir, "server_key.pem")
        pwd_file = os.path.join(self.temp_dir, "cert_pwd")

        with open(cert_file, 'w') as f:
            f.write("test")
        with open(key_file, 'w') as f:
            f.write("test")
        with open(pwd_file, 'w') as f:
            f.write("test")

        self.generator._set_file_permissions(self.temp_dir)

        if os.name != 'nt':
            self.assertEqual(os.stat(cert_file).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(key_file).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(pwd_file).st_mode & 0o777, 0o600)

    def test_generate_password(self):
        password = self.generator._generate_password()
        self.assertIsInstance(password, bytes)
        self.assertGreaterEqual(len(password), 8)

    @patch('common.cert.certificate_generator.audit_logger')
    def test_audit_log_generation(self, mock_audit_logger):
        self.generator._audit_log_generation(self.temp_dir)
        mock_audit_logger.audit.assert_called_once()

        call_args = mock_audit_logger.audit.call_args[0][0]
        self.assertEqual(call_args["operation_name"], "Generate TLS Certificate")
        self.assertEqual(call_args["result"], "Success")
        self.assertEqual(call_args["object_name"], "Certificate")

    def test_generate_certificates_with_data_signing(self):
        cert_usage = ["serverAuth", "dataSigning"]
        result = self.generator.generate_certificates(self.temp_dir, cert_usage)
        self.assertTrue(result)

        cert_file = os.path.join(self.temp_dir, "server.cer")
        x509_obj = parse_cer_certificate(cert_file)
        self.assertIsNotNone(x509_obj)

    def test_generate_certificates_invalid_directory(self):
        invalid_dir = os.path.join(self.temp_dir, "nonexistent", "nested", "dir")
        cert_usage = ["serverAuth"]
        result = self.generator.generate_certificates(invalid_dir, cert_usage)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(invalid_dir))


if __name__ == '__main__':
    unittest.main()
