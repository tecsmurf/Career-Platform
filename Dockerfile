FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ .

# Copy MCP servers (email reader needs to be accessible)
COPY mcp_servers/ ./mcp_servers/

# Run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
