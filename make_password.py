"""Generate a salted administrator password hash without echoing the password."""
import getpass
from security import hash_password
if __name__ == '__main__':
    first = getpass.getpass('New administrator password: ')
    second = getpass.getpass('Repeat password: ')
    if first != second or len(first) < 12:
        raise SystemExit('Use matching passwords with at least 12 characters.')
    print(hash_password(first))
