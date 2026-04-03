import jwt
from datetime import datetime, timedelta

SECRET_KEY = "7b4c9e2a8f1d6c3b5e9a2f8c7b4d9e6a3f1b8c7d5e9a2f8c7b4d9e6a3f1b8c"
ALGORITHM = "HS256"

def create_access_token():
    expire = datetime.utcnow() + timedelta(minutes=480)
    to_encode = {"sub": "admin", "username": "admin", "is_admin": True, "iss": "gov-backend", "aud": "gov-platform", "exp": expire}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    print(encoded_jwt)

create_access_token()
