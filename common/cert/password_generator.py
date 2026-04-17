import random
import string


class PasswordGenerator:
    """口令生成器，负责生成符合复杂度要求的随机口令"""

    DIGITS = string.digits
    UPPER = string.ascii_uppercase
    LOWER = string.ascii_lowercase
    SPECIAL = "`~!@#$%^&*()-_=+|[{}];:'\",<.>/? "

    def __init__(self):
        self.all_chars = self.DIGITS + self.UPPER + self.LOWER + self.SPECIAL

    def generate_password(self, length: int = 16) -> str:
        """
        生成符合复杂度要求的随机口令
        :param length: 口令长度，默认16
        :return: 随机口令
        """
        if length < 8:
            raise ValueError("Password length must be at least 8")

        password = []
        char_types = [self.DIGITS, self.UPPER, self.LOWER, self.SPECIAL]
        random.shuffle(char_types)

        for i in range(length):
            if i < 4:
                password.append(self._generate_random_char(char_types[i]))
            else:
                password.append(self._generate_random_char(self.all_chars))

        random.shuffle(password)
        return ''.join(password)

    def _generate_random_char(self, chars: str) -> str:
        """
        从指定字符集中生成一个随机字符
        :param chars: 字符集
        :return: 随机字符
        """
        return random.choice(chars)
