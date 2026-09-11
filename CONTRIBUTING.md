# Contributing

1. Create a branch for the change.
2. Keep secrets, cookies, tokens and local `data/` files out of commits.
3. Run `python -m pytest -q` and `python -m compileall -q app installer.py`.
4. Keep Playerok-specific network calls behind `app/playerok`.
5. Do not bypass CAPTCHA, 2FA or platform protections.
