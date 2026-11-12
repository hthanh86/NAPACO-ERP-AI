"""Run the employee administration tool inside the local backend."""
import subprocess
import sys
from manage import DOCKER

if __name__ == '__main__':
    sys.exit(subprocess.call([DOCKER, 'exec', 'napaco-backend', 'python', '-m', 'app.auth.manage_users', *sys.argv[1:]]))
