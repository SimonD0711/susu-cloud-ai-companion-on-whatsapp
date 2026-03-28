#!/usr/bin/env python3
import base64
import getpass
import hashlib
import secrets
import sys


def main():
    password = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Admin password: ")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000, dklen=32)
    print(f"SUSU_ADMIN_PASSWORD_SALT_B64={base64.b64encode(salt).decode('ascii')}")
    print(f"SUSU_ADMIN_PASSWORD_HASH_B64={base64.b64encode(digest).decode('ascii')}")
    print(f"SUSU_ADMIN_SESSION_SECRET={secrets.token_hex(32)}")


if __name__ == "__main__":
    main()
