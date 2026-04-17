import re
import getpass


def validate_password_complexity(password: str) -> tuple[bool, str]:
    min_length = 8
    digit_pattern = re.compile(r'[0-9]')
    upper_pattern = re.compile(r'[A-Z]')
    lower_pattern = re.compile(r'[a-z]')
    special_pattern = re.compile(r'[`~!@#$%^&*()-_=+|\[\{\}\];:\'",<.>/? ]')

    if len(password) < min_length:
        return False, f"至少{min_length}个字符"

    char_types = sum(bool(re.search(pattern, password)) for pattern in
                     [digit_pattern, upper_pattern, lower_pattern, special_pattern])
    if char_types < 2:
        return False, "包含至少两种字符类型"

    return True, ""


def input_password_with_validation(prompt: str) -> str:
    while True:
        password = getpass.getpass(f"{prompt}: ")
        result, error = validate_password_complexity(password)
        if not result:
            print(f"私钥口令复杂度过低，请确认是否需要继续使用该口令 (y/n): ", end='')
            confirm = input().strip().lower()
            if confirm != 'y':
                continue
        return password