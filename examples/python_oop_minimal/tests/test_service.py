import unittest

from src.service import UserService, check_token


class TokenFlowTest(unittest.TestCase):
    def test_check_token(self) -> None:
        self.assertTrue(check_token(" Demo "))

    def test_validate_token(self) -> None:
        self.assertTrue(UserService.validate_token(" Demo "))


if __name__ == "__main__":
    unittest.main()
