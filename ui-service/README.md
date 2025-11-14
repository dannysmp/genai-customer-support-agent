# UI Service

A lightweight, containerized Streamlit application that provides a clean and responsive web interface for the Customer Support Agent. It connects directly to the backend [`customer-support-service`](../customer-support-service), enabling users to interact with the agentic reasoning system through a conversational chat interface. The UI is designed for clarity and usability, maintaining session state, displaying contextual responses, and performing real-time health checks on the backend service.

## ✅ 1. Requirements

- **Docker** installed locally.
- **Internet connection** for image builds and dependency downloads.
- The `customer-support-service` must be running and reachable (`http://localhost:8000` by default).
- Environment variables configured through a `.env` file:
  - `BACKEND_BASE_URL` providing the base URL of the backend API used to communicate with the `customer-support-service`.
  - `STREAMLIT_SERVER_PORT` defining the port for the Streamlit application (`8501` by default).
  - `STREAMLIT_SERVER_ADDRESS` defining the network interface for Streamlit to listen on (`0.0.0.0` for Docker deployments).

## ⚙️ 2. Deployment with Docker

### 2.1 Clone the Repository

Clone the repository to your local machine:

```bash
git clone https://github.com/dannysmp/customer-support-agent.git

cd customer-support-agent/ui-service
```

### 2.2 Build the Docker Image

In the directory `ui-service`, run the following command to build the Docker image:

```bash
docker build -t ui-service .
```

This command builds a production-ready image of the Streamlit interface and packages it into a lightweight container named `ui-service`.

### 2.3 Run the Docker Container

After building the image, run the container and expose the interface on port `8501`:

```bash
docker run -p 8501:8501 --env-file ./.env ui-service
```

The application will be available at: [`http://localhost:8501`](http://localhost:8501)

## 💻 3. Application Features

The UI provides a conversational interface that allows users to interact directly with the Customer Support Agent through natural language. It offers a minimal and user-friendly layout that dynamically displays agent responses and system messages in real time.

From startup, the interface automatically connects to the backend, manages session context, and ensures stable communication through a real-time health monitoring loop.

### Core Features

- **Conversational Chat Interface:** Enables users to submit questions or requests in natural language and receive grounded, policy-compliant answers from the backend agent.
- **Session State Management:** Maintains conversation context within each user session to ensure continuity in dialogue flow.
- **Health Monitoring:** Periodically checks the status of the backend `customer-support-service` and displays connection status indicators.
- **Automatic Refresh:** Refreshes the interface at regular intervals to ensure real-time synchronization with the agent’s state.
- **Reset Capability:** Allows users to reset the current session, clearing history and starting a new conversation with a clean context.

### Backend Communication

All frontend interactions are processed through the following backend endpoints:

- `GET /health` – Verifies that the backend service is running and reachable.
- `POST /chat` – Sends user messages to the backend agent and returns structured responses.
- `POST /reset` – Resets the current conversation session to its initial state.

## 📁 4. Project Structure

The service directory is organized as follows:

```
📂 ui-service                              # Streamlit web interface for the Customer Support Agent
├── 📄 .env                                # Example environment configuration file
├── 📄 Dockerfile                          # Dockerfile for UI service
├── 📄 README.md                           # Service documentation
├── 📄 app.py                              # Streamlit application logic
└── 📄 requirements.txt                    # Python dependencies for the UI
```

## 🔄 5. CI/CD Integration

This service is automatically validated, built, and deployed through GitHub Actions using a single workflow:

- The pipeline defined in `.github/workflows/main_pipeline.yml` runs on every push to the `main` branch.
- It performs the following stages:
  1. Executes unit tests for the `customer-support-service`.
  2. Builds Docker images for both services and pushes them to Amazon ECR.
  3. Connects securely to the target AWS EC2 instance and deploys both services via Docker.
- During deployment, the workflow injects all required environment variables from the repository’s GitHub Secrets, ensuring secure and consistent configuration across environments. These include credentials, ports, hostnames, and service URLs required by both the backend and the UI.
  Examples: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `BACKEND_PORT`, `FRONTEND_PORT`, `OPENAI_API_KEY`, and `S3_BUCKET`.
- Both the `customer-support-service` and `ui-service` containers are built and deployed using the latest image tag from Amazon ECR, ensuring each deployment reflects the most recent validated build.
- The frontend container listens on the configured frontend port (`8501` by default) and communicates with the backend through the `BACKEND_BASE_URL` defined in the GitHub Secrets.
- Logs from the deployment process are printed to the CI console, and any failure triggers an automatic stop and cleanup of previous containers.

CI/CD workflow definition:  
- [`.github/workflows/main_pipeline.yml`](../.github/workflows/main_pipeline.yml)

## 📦 6. Notes

- This frontend assumes the `customer-support-service` backend is accessible at `localhost` during local development. For cloud or production deployments, configure environment-based proxies or a reverse proxy (e.g., NGINX or Traefik) to correctly route API requests.
- Ensure the `customer-support-service` container is running and reachable before launching the UI, as all conversational interactions depend on it.
- The interface is reactive and supports automatic refresh, real-time connection checks, and session management, ensuring a smooth conversational experience.
- Data persistence is handled exclusively by the backend. The UI only visualizes responses and does not store any customer data.

Together, these safeguards guarantee that the system operates consistently, securely, and in full alignment with its agentic and data-driven design.

## 📬 7. Contact

- **Danny Martinez**
   - **Email**: danny.martinez@u.icesi.edu.co, stevenmartinez880@gmail.com