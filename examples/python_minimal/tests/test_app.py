import unittest

from src.app import login


class LoginFlowTest(unittest.TestCase):
    def test_login_creates_session(self):
        result = login("demo", "swordfish")
        self.assertTrue(result["ok"])
        self.assertTrue(result["session"].startswith("session-"))

    def test_login_rejects_bad_credentials(self):
        result = login("demo", "wrong")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid-credentials")


if __name__ == "__main__":
    unittest.main()
