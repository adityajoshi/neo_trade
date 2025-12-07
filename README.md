# neo_trade

A small trading helper project — minimal starter that uses environment
variables from `sample.env` and runs `main.py`.

**Overview**
- **Project**: `neo_trade` — lightweight script-based trading helper.
- **Main file**: `main.py` — entry point for the application.
- **Env example**: `sample.env` — template for required environment variables.

**Environment Variables**
The project reads credentials and settings from environment variables. A
copy of the variables is provided in `sample.env`:

```
CONSUMER_KEY="xxxx"
CONSUMER_SECRET="xxxx"
USER_ID="xxxx"
PASSWORD="xxxx"
TOTP="xxxx"
ENV="prod"
```

- **CONSUMER_KEY / CONSUMER_SECRET**: API credentials for the trading
  platform.
- **USER_ID / PASSWORD**: User login credentials.
- **TOTP**: Time-based one-time password (if MFA/TOTP is required).
- **ENV**: Environment tag (e.g., `prod`, `staging`, `dev`).

Replace placeholder values with real credentials before running.

**Requirements**
- Python 3.8+ (use a virtual environment).
- If your project needs third-party packages, add a `requirements.txt`.

**Setup**
1. Create a virtual environment and activate it:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. (Optional) Install dependencies if you add a `requirements.txt`:

```bash
pip install -r requirements.txt
```

3. Copy `sample.env` to `.env` (or set environment variables directly):

```bash
cp sample.env .env
# then edit .env to add real values
```

4. Export variables for the current shell (simple approach):

```bash
export $(grep -v '^#' sample.env | xargs)
```

Alternatively, use a dotenv loader (e.g., `python-dotenv`) in `main.py`.

**Run**

Run the application with:

```bash
python main.py
```

**Files**
- `main.py` — application entry point
- `sample.env` — environment variable template
- `README.md` — this file

**Next steps**
- Add `requirements.txt` to pin dependencies.
- Add a short CONTRIBUTING or development guide if the project grows.
- Add tests and a CI workflow for automated checks.

**Contact / Support**
If you need help, open an issue in the repository or contact the author.
