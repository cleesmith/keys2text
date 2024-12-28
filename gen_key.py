from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(key.decode())
# 
# or use:
# https://fernetkeygen.com/

import secrets
# generate a URL-safe secret
secret = secrets.token_urlsafe(32)
print(secret)

secret = secrets.token_urlsafe(64)
print(secret)

