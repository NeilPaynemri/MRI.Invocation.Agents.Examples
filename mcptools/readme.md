the tool used by the provided example is the unprotected mcp_calculator_tool.py
the others kept for reference

you can connect to the mcp tool via a devtunnel from azure to your local machine

## Environment Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your OAuth values before running the OAuth-protected server.

## Dev Tunnels

# One-time setup: create a persistent tunnel for port 3001/8000/etc
devtunnel create --allow-anonymous
devtunnel port create -p 8000

devtunnel host -p 8000 --allow-anonymous
py mcp_xxxxxx_server.py