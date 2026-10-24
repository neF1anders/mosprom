import os
import subprocess
import sys

migration_env = dict(os.environ, DATABASE_URL=os.environ["TEST_DATABASE_URL"])
subprocess.run(["alembic", "upgrade", "head"], env=migration_env, check=True)

commands = [
    [sys.executable, "scripts/make_fixtures.py"],
    [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--cov=src",
        "--cov-report=term-missing",
        "--cov-fail-under=80",
    ],
    ["ruff", "check", "."],
    ["mypy", "src/backend"],
    ["npm", "--prefix", "src/web", "run", "test:unit"],
    ["npm", "--prefix", "src/web", "run", "test:e2e"],
]
for command in commands:
    result = subprocess.run(command, env=os.environ.copy(), check=False)
    if result.returncode:
        sys.exit(result.returncode)
