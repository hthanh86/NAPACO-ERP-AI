import argparse
import sys
from .db import Session
from .models import User
from .auth import hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', default='local-admin')
    parser.add_argument('--name', default='Quản trị local')
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip('\n')
    if len(password) < 14:
        raise ValueError('Password must contain at least 14 characters.')
    with Session.begin() as db:
        if db.get(User, args.user):
            raise ValueError('User already exists; password has not been changed.')
        db.add(User(id=args.user, name=args.name, role='LOCAL_ADMIN', active=True,
                    password_hash=hash_password(password)))
    print('Created local development administrator. No imported employee permissions changed.')


if __name__ == '__main__':
    main()
