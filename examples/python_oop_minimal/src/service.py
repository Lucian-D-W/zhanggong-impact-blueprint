class UserService:
    @classmethod
    def normalize_token(cls, token: str) -> str:
        return token.strip().lower()

    @classmethod
    def validate_token(cls, token: str) -> bool:
        normalized = cls.normalize_token(token)
        return normalized == "demo"


def check_token(token: str) -> bool:
    return UserService.validate_token(token)

