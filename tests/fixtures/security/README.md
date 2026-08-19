# Security Test Fixtures

This directory contains test cases for repository path validation and secure reading.

## Test Cases

- `../secret.txt` - Directory traversal
- `/etc/passwd` - Absolute POSIX path
- `C:\Windows\System32` - Absolute Windows path
- `src/../../../etc/passwd` - Deep traversal
- `.env` - Secret file
- `.env.production` - Environment file
- `private.key` - Private key
- `credentials.json` - Credentials file
- `binary.bin` - Binary file
- `large.txt` - Oversized file (>1MB)
- `unicode_文件.py` - Unicode filename
- `crlf.txt` - CRLF line endings
- Symlinks pointing outside repo