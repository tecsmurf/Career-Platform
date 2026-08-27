FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached if requirements don't change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy MCP servers (they live outside backend/ in the repo)
# This is handled by Render's root directory setting
# MCP server path: mcp_servers/email_reader/server.py

# Run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
