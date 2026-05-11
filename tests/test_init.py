import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from agent_registry.init import InitCommand


class TestInitCommand(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "server.conf")

    def tearDown(self):
        if os.path.exists(self.config_file):
            os.remove(self.config_file)
        os.rmdir(self.temp_dir)

    def _create_init_command(self):
        init_cmd = InitCommand()
        init_cmd.config_file = self.config_file
        init_cmd.existing_config = {}
        return init_cmd

    def _create_init_command_with_config(self, config_content: str):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        init_cmd = InitCommand()
        init_cmd.config_file = self.config_file
        init_cmd.existing_config = init_cmd._load_existing_config()
        return init_cmd

    def test_load_existing_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write("enable_https=true\n")
            f.write("ssl_certfile=/path/to/cert.cer\n")
            f.write("registry.sign.enabled=false\n")
            f.write("# comment line\n")
            f.write("  spaced_key = spaced_value  \n")

        init_cmd = self._create_init_command()
        config = init_cmd._load_existing_config()

        self.assertEqual(config['enable_https'], 'true')
        self.assertEqual(config['ssl_certfile'], '/path/to/cert.cer')
        self.assertEqual(config['registry.sign.enabled'], 'false')
        self.assertEqual(config['spaced_key'], 'spaced_value')
        self.assertNotIn('# comment line', config)

    def test_load_existing_config_empty_file(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write("")

        init_cmd = self._create_init_command()
        config = init_cmd._load_existing_config()

        self.assertEqual(config, {})

    def test_load_existing_config_no_file(self):
        init_cmd = self._create_init_command()
        init_cmd.config_file = "/nonexistent/path/server.conf"
        config = init_cmd._load_existing_config()

        self.assertEqual(config, {})

    def test_save_config_to_file_new_file(self):
        init_cmd = self._create_init_command()
        config = {
            'enable_https': 'true',
            'ssl_certfile': '/path/to/cert.cer',
            'ssl_keyfile': '/path/to/key.pem',
            'ssl_keyfile_password': '/path/to/key_pwd',
            'ssl_ca_certs': '/path/to/ca.cer',
            'ssl_cert_certs': '',
            'ssl_verify_client': 'true',
            'sign_certfile': '/path/to/sign.cer',
            'sign_keyfile': '/path/to/sign_key.pem',
            'sign_keyfile_password': '/path/to/sign_key_pwd',
            'registry.sign.enabled': 'true',
            'signature_validation_enabled': 'true'
        }

        init_cmd.save_config_to_file(config)

        self.assertTrue(os.path.exists(self.config_file))
        with open(self.config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('enable_https=true', content)
        self.assertIn('ssl_certfile=/path/to/cert.cer', content)
        self.assertIn('ssl_keyfile=/path/to/key.pem', content)
        self.assertIn('sign_certfile=/path/to/sign.cer', content)
        self.assertIn('registry.sign.enabled=true', content)
        self.assertIn('signature_validation_enabled=true', content)

    def test_save_config_to_file_update_existing(self):
        init_cmd = self._create_init_command()

        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write("enable_https=false\n")
            f.write("ssl_certfile=/old/cert.cer\n")
            f.write("ssl_keyfile=/old/key.pem\n")
            f.write("ssl_keyfile_password=/old/key_pwd\n")
            f.write("ssl_ca_certs=/old/ca.cer\n")
            f.write("ssl_cert_certs=\n")
            f.write("ssl_verify_client=false\n")
            f.write("sign_certfile=/old/sign.cer\n")
            f.write("sign_keyfile=/old/sign_key.pem\n")
            f.write("sign_keyfile_password=/old/sign_key_pwd\n")
            f.write("registry.sign.enabled=false\n")
            f.write("signature_validation_enabled=false\n")

        config = {
            'enable_https': 'true',
            'ssl_certfile': '/new/cert.cer',
            'ssl_keyfile': '/new/key.pem',
            'ssl_keyfile_password': '/new/key_pwd',
            'ssl_ca_certs': '/new/ca.cer',
            'ssl_cert_certs': '',
            'ssl_verify_client': 'true',
            'sign_certfile': '/new/sign.cer',
            'sign_keyfile': '/new/sign_key.pem',
            'sign_keyfile_password': '/new/sign_key_pwd',
            'registry.sign.enabled': 'true',
            'signature_validation_enabled': 'true'
        }

        init_cmd.save_config_to_file(config)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('enable_https=true', content)
        self.assertIn('ssl_certfile=/new/cert.cer', content)
        self.assertIn('ssl_keyfile=/new/key.pem', content)
        self.assertIn('ssl_verify_client=true', content)
        self.assertIn('sign_certfile=/new/sign.cer', content)
        self.assertIn('registry.sign.enabled=true', content)
        self.assertIn('signature_validation_enabled=true', content)

        self.assertNotIn('enable_https=false', content)
        self.assertNotIn('/old/cert.cer', content)
        self.assertNotIn('ssl_verify_client=false', content)

    def test_save_config_to_file_preserve_other_config(self):
        init_cmd = self._create_init_command()

        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write("other_config=value1\n")
            f.write("enable_https=false\n")
            f.write("ssl_certfile=/old/cert.cer\n")
            f.write("ssl_keyfile=/old/key.pem\n")
            f.write("custom_ssl_option=custom_value\n")
            f.write("sign_certfile=/old/sign.cer\n")
            f.write("other_option=other_value\n")

        config = {
            'enable_https': 'true',
            'ssl_certfile': '/new/cert.cer',
            'ssl_keyfile': '/new/key.pem',
            'ssl_keyfile_password': '/new/key_pwd',
            'ssl_ca_certs': '/new/ca.cer',
            'ssl_verify_client': 'true',
            'sign_certfile': '/new/sign.cer',
            'sign_keyfile': '/new/sign_key.pem',
            'sign_keyfile_password': '/new/sign_key_pwd',
            'registry.sign.enabled': 'true',
            'signature_validation_enabled': 'true'
        }

        init_cmd.save_config_to_file(config)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('other_config=value1', content)
        self.assertIn('custom_ssl_option=custom_value', content)
        self.assertIn('other_option=other_value', content)

    def test_save_config_to_file_partial_update(self):
        init_cmd = self._create_init_command()

        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write("enable_https=true\n")
            f.write("ssl_certfile=/old/cert.cer\n")
            f.write("ssl_keyfile=/old/key.pem\n")
            f.write("ssl_verify_client=true\n")
            f.write("sign_certfile=/old/sign.cer\n")
            f.write("sign_keyfile=/old/sign_key.pem\n")
            f.write("registry.sign.enabled=true\n")
            f.write("signature_validation_enabled=true\n")

        config = {
            'enable_https': 'false',
            'registry.sign.enabled': 'false',
            'signature_validation_enabled': 'false'
        }

        init_cmd.save_config_to_file(config)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('enable_https=false', content)
        self.assertIn('ssl_certfile=/old/cert.cer', content)
        self.assertIn('ssl_keyfile=/old/key.pem', content)
        self.assertIn('sign_certfile=/old/sign.cer', content)
        self.assertIn('registry.sign.enabled=false', content)
        self.assertIn('signature_validation_enabled=false', content)

    def test_save_config_to_file_https_disabled(self):
        init_cmd = self._create_init_command()

        config = {
            'enable_https': 'false',
            'registry.sign.enabled': 'true',
            'sign_certfile': '/path/to/sign.cer',
            'sign_keyfile': '/path/to/sign_key.pem',
            'sign_keyfile_password': '/path/to/sign_key_pwd',
            'signature_validation_enabled': 'true'
        }

        init_cmd.save_config_to_file(config)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('enable_https=false', content)
        self.assertIn('registry.sign.enabled=true', content)
        self.assertIn('sign_certfile=/path/to/sign.cer', content)
        self.assertIn('signature_validation_enabled=true', content)

    def test_registry_sign_enabled_false(self):
        init_cmd = self._create_init_command()

        config = {
            'enable_https': 'true',
            'ssl_certfile': '/path/to/cert.cer',
            'ssl_keyfile': '/path/to/key.pem',
            'ssl_keyfile_password': '/path/to/key_pwd',
            'ssl_ca_certs': '/path/to/ca.cer',
            'ssl_verify_client': 'true',
            'registry.sign.enabled': 'false',
            'signature_validation_enabled': 'true'
        }

        init_cmd.save_config_to_file(config)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('registry.sign.enabled=false', content)
        self.assertNotIn('sign_certfile', content)
        self.assertNotIn('sign_keyfile', content)

    def test_input_path_with_default_empty_input(self):
        init_cmd = self._create_init_command()
        init_cmd.validate_cert_path = MagicMock(return_value=(True, ""))
        init_cmd.validate_file_permissions = MagicMock(return_value=(True, ""))

        with patch('builtins.input', return_value=''):
            result = init_cmd.input_path("Enter path", "/default/path.cer", ".cer")
            self.assertEqual(result, "/default/path.cer")

    def test_input_path_with_default_new_input(self):
        init_cmd = self._create_init_command()
        init_cmd.validate_cert_path = MagicMock(return_value=(True, ""))
        init_cmd.validate_file_permissions = MagicMock(return_value=(True, ""))

        with patch('builtins.input', return_value='/new/path.cer'):
            result = init_cmd.input_path("Enter path", "/default/path.cer", ".cer")
            self.assertEqual(result, "/new/path.cer")

    def test_input_path_track_change_unchanged(self):
        init_cmd = self._create_init_command()
        init_cmd.validate_cert_path = MagicMock(return_value=(True, ""))
        init_cmd.validate_file_permissions = MagicMock(return_value=(True, ""))

        with patch('builtins.input', return_value=''):
            path, changed = init_cmd.input_path("Enter path", "/default/path.pem", ".pem", track_change=True)
            self.assertEqual(path, "/default/path.pem")
            self.assertFalse(changed)

    def test_input_path_track_change_changed(self):
        init_cmd = self._create_init_command()
        init_cmd.validate_cert_path = MagicMock(return_value=(True, ""))
        init_cmd.validate_file_permissions = MagicMock(return_value=(True, ""))

        with patch('builtins.input', return_value='/new/path.pem'):
            path, changed = init_cmd.input_path("Enter path", "/default/path.pem", ".pem", track_change=True)
            self.assertEqual(path, "/new/path.pem")
            self.assertTrue(changed)

    def test_init_command_https_disabled_skips_tls(self):
        init_cmd = self._create_init_command_with_config("enable_https=false\n")

        mock_inputs = ['n', 'y', 'y']
        with patch('builtins.input', side_effect=mock_inputs):
            with patch.object(init_cmd, 'config_tls_cert') as mock_tls:
                with patch.object(init_cmd, 'config_sign_cert') as mock_sign:
                    mock_sign.return_value = {
                        'sign_certfile': '/sign.cer',
                        'sign_keyfile': '/sign_key.pem',
                        'sign_keyfile_password': '/sign_pwd'
                    }
                    init_cmd.init_command()
                    mock_tls.assert_not_called()
                    mock_sign.assert_called_once()

    def test_init_command_registry_sign_disabled_skips_sign(self):
        init_cmd = self._create_init_command_with_config("enable_https=true\n")

        mock_inputs = ['y', 'n', 'y']
        with patch('builtins.input', side_effect=mock_inputs):
            with patch.object(init_cmd, 'config_tls_cert') as mock_tls:
                with patch.object(init_cmd, 'config_sign_cert') as mock_sign:
                    mock_tls.return_value = {
                        'ssl_certfile': '/cert.cer',
                        'ssl_keyfile': '/key.pem',
                        'ssl_keyfile_password': '/key_pwd',
                        'ssl_ca_certs': '/ca.cer',
                        'ssl_cert_certs': '',
                        'ssl_verify_client': 'true'
                    }
                    init_cmd.init_command()
                    mock_tls.assert_called_once()
                    mock_sign.assert_not_called()

    def test_init_command_default_values_from_existing_config(self):
        config_content = (
            "enable_https=false\n"
            "registry.sign.enabled=false\n"
            "signature_validation_enabled=false\n"
            "ssl_certfile=/existing/cert.cer\n"
            "ssl_keyfile=/existing/key.pem\n"
        )
        init_cmd = self._create_init_command_with_config(config_content)

        self.assertEqual(init_cmd.existing_config.get('enable_https'), 'false')
        self.assertEqual(init_cmd.existing_config.get('registry.sign.enabled'), 'false')
        self.assertEqual(init_cmd.existing_config.get('signature_validation_enabled'), 'false')
        self.assertEqual(init_cmd.existing_config.get('ssl_certfile'), '/existing/cert.cer')
        self.assertEqual(init_cmd.existing_config.get('ssl_keyfile'), '/existing/key.pem')

    def test_config_tls_cert_keyfile_unchanged_preserves_password(self):
        init_cmd = self._create_init_command_with_config(
            "ssl_certfile=/cert.cer\n"
            "ssl_keyfile=/key.pem\n"
            "ssl_keyfile_password=/existing_pwd\n"
            "ssl_ca_certs=/ca.cer\n"
        )

        with patch('builtins.input', side_effect=['', '', '', '', 'y']):
            with patch.object(init_cmd, 'validate_cert_path', return_value=(True, "")):
                with patch.object(init_cmd, 'validate_file_permissions', return_value=(True, "")):
                    config = init_cmd.config_tls_cert()

                    self.assertEqual(config['ssl_keyfile_password'], '/existing_pwd')

    def test_config_sign_cert_keyfile_unchanged_preserves_password(self):
        init_cmd = self._create_init_command_with_config(
            "sign_certfile=/sign.cer\n"
            "sign_keyfile=/sign_key.pem\n"
            "sign_keyfile_password=/existing_sign_pwd\n"
        )

        with patch('builtins.input', side_effect=['', '']):
            with patch.object(init_cmd, 'validate_cert_path', return_value=(True, "")):
                with patch.object(init_cmd, 'validate_file_permissions', return_value=(True, "")):
                    config = init_cmd.config_sign_cert()

                    self.assertEqual(config['sign_keyfile_password'], '/existing_sign_pwd')


if __name__ == '__main__':
    unittest.main()