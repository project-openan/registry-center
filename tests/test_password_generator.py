import unittest
import string
from common.cert.password_generator import PasswordGenerator


class TestPasswordGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = PasswordGenerator()

    def test_generate_password_default_length(self):
        password = self.generator.generate_password()
        self.assertEqual(len(password), 16)

    def test_generate_password_custom_length(self):
        password = self.generator.generate_password(20)
        self.assertEqual(len(password), 20)

    def test_generate_password_minimum_length(self):
        password = self.generator.generate_password(8)
        self.assertEqual(len(password), 8)

    def test_generate_password_too_short(self):
        with self.assertRaises(ValueError):
            self.generator.generate_password(7)

    def test_generate_password_contains_digits(self):
        password = self.generator.generate_password()
        self.assertTrue(any(c in string.digits for c in password))

    def test_generate_password_contains_uppercase(self):
        password = self.generator.generate_password()
        self.assertTrue(any(c in string.ascii_uppercase for c in password))

    def test_generate_password_contains_lowercase(self):
        password = self.generator.generate_password()
        self.assertTrue(any(c in string.ascii_lowercase for c in password))

    def test_generate_password_contains_special(self):
        password = self.generator.generate_password()
        special_chars = "`~!@#$%^&*()-_=+|[{}];:'\",<.>/? "
        self.assertTrue(any(c in special_chars for c in password))

    def test_generate_password_uniqueness(self):
        passwords = [self.generator.generate_password() for _ in range(10)]
        unique_passwords = set(passwords)
        self.assertEqual(len(unique_passwords), 10)

    def test_generate_random_char(self):
        char = self.generator._generate_random_char(string.digits)
        self.assertIn(char, string.digits)

        char = self.generator._generate_random_char(string.ascii_uppercase)
        self.assertIn(char, string.ascii_uppercase)

        char = self.generator._generate_random_char(string.ascii_lowercase)
        self.assertIn(char, string.ascii_lowercase)

        special_chars = "`~!@#$%^&*()-_=+|[{}];:'\",<.>/? "
        char = self.generator._generate_random_char(special_chars)
        self.assertIn(char, special_chars)


if __name__ == '__main__':
    unittest.main()
