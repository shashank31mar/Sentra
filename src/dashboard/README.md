# Sentra Dashboard

Streamlit-based UI for monitoring and managing AI agent security.

## Project Structure

```
dashboard/
├── app.py                          # Main Streamlit app
├── requirements.txt                # Python dependencies
├── config/
│   ├── __init__.py
│   └── settings.py                 # Configuration loader
├── tabs/
│   ├── __init__.py
│   ├── overview_tab.py             # Tab 1: Overview
│   ├── agents_tab.py               # Tab 2: Agents
│   ├── chats_tab.py                # Tab 3: Chats
│   ├── audit_tab.py                # Tab 4: Audit
│   └── security_tab.py             # Tab 5: Security
├── components/                     # Reusable UI components
├── services/                       # API clients
├── utils/                          # Utility functions
├── static/
│   └── styles.css                  # Custom CSS
└── tests/                          # Unit tests
```

## Local Development

### Prerequisites

- Python 3.11+
- pip

### Setup

```bash
# Navigate to dashboard directory
cd src/dashboard

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run Locally

```bash
# Run Streamlit app
streamlit run app.py

# App will be available at http://localhost:8501
```

### Environment Variables

```bash
# Optional - defaults are provided
export ENVIRONMENT=dev
export AWS_REGION=us-east-1
export AWS_PROFILE=sentra
export SECURITY_CONTROLLER_URL=http://security-controller.sentra.internal:8080
export LOG_LEVEL=INFO
```

## Docker Build & Test

### Build Image

```bash
# Build Docker image (from project root)
docker build -f docker/dashboard/Dockerfile -t sentra/dashboard:local .
```

### Run Container

```bash
# Run container locally
docker run -p 8501:8501 \
  -e AWS_REGION=us-east-1 \
  -e SECURITY_CONTROLLER_URL=http://security-controller.sentra.internal:8080 \
  sentra/dashboard:local

# Access at http://localhost:8501
```

### Test Health Check

```bash
# Check container health
docker ps

# Should show "healthy" status after ~5 seconds
```

## Deployment

### Deploy to ECS

```bash
# Build and push to ECR (from project root)
python scripts/build_and_push_image.py --service dashboard --milestone 1

# ECS automatically pulls new image and performs rolling update
```

**Note:** The build script automatically:
- Uses `docker/dashboard/Dockerfile`
- Builds from project root context
- Tags as `milestone-N` and `latest`
- Pushes to ECR repository: `sentra/dashboard`

## Development Status

### Milestone 1: Base Setup ✅
- [x] Project structure created
- [x] Tab navigation implemented
- [x] Dockerfile created (in docker/dashboard/)
- [x] Local testing verified

### Milestone 2: Overview Tab UI (In Progress)
- [ ] Agent Status component
- [ ] Security Metrics component
- [ ] Activity Feed component
- [ ] Rollback Panel component

## Features

### Current (Milestone 1)
- ✅ 5-tab navigation (Overview, Agents, Chats, Audit, Security)
- ✅ Custom CSS styling
- ✅ Auto-refresh toggle
- ✅ Session state management

### Coming Soon
- 📊 Real-time monitoring dashboard
- 🤖 Agent management interface
- 💬 Interactive chat with agents
- 📋 Complete audit log
- 🛡️ Threat analysis and Sigma rules

## Testing

```bash
# Run unit tests (when available)
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=. --cov-report=html
```

## Troubleshooting

### Port Already in Use

```bash
# Kill process using port 8501
lsof -ti:8501 | xargs kill -9

# Or use a different port
streamlit run app.py --server.port=8502
```

### Import Errors

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Docker Build Fails

```bash
# Clean Docker cache
docker system prune -a

# Rebuild without cache
docker build --no-cache -t sentra/dashboard:local .
```

## References

- [LLD 04: Dashboard v2](../../lld/04-dashboard-v2.md)
- [Workstream 4: Dashboard Tasks](../../tasks/workstream-4-dashboard.md)
- [Best Practices](../../best-practices.md)
