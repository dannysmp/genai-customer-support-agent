# Customer Support Service

A containerized Python application that runs an agentic, data-grounded customer support system designed for intelligent and context-aware assistance. The service leverages a LangChain-powered Retrieval-Augmented Generation (RAG) core enhanced with deterministic agentic reasoning, combining structured JSON validation, dynamic prompt control, and semantic retrieval across Orders, Product Catalog, Returns Policy, and FAQs.

This hybrid architecture enables the agent to interpret user intent, perform logical reasoning over structured datasets, and generate responses that are both factually grounded and policy-compliant, delivering a fully autonomous customer support experience.

## ✅ 1. Requirements

- **Docker** installed locally.
- **Internet connection** for image builds and model downloads.
- A local **Chroma** vector database powers the semantic retrieval layer. The agentic Retrieval-Augmented Generation module automatically indexes and correlates information from:
  - **Orders:** Transactional and fulfillment records used for order tracking and delivery validation.
  - **Product Catalog:** Categorized product information, including specifications, perishability attributes, and defined return windows.
  - **Returns Policy & FAQs:** Unstructured business rules defining eligibility criteria and operational exceptions.
- **LangChain** orchestrates both the retrieval layer and the agent’s decision-making workflow.
- **HuggingFace Embeddings** provide multilingual semantic encoding for cross-lingual comprehension.
- **Agentic orchestration framework** based on modern LLM infrastructure, enabling:
  - Deterministic JSON-structured outputs for every model response.
  - Context-driven state transitions to manage reasoning over orders, products, and policies.
  - Built-in error handling and fallback mechanisms ensuring stable, predictable conversational behavior.
- Environment variables configured through a `.env` file:
  - `OPENAI_API_KEY` providing access to the **OpenAI API** used for the conversational and reasoning model.

## ⚙️ 2. Deployment with Docker

### 2.1 Clone the Repository

Clone the repository to your local machine:

```bash
git clone https://github.com/dannysmp/customer-support-agent.git

cd customer-support-agent/customer-support-service
```

### 2.2 Build the Docker Image

The `customer-support-service` can be containerized and executed in two modes:
- **Command-line Interface** for interactive terminal sessions.
- **Web API Interface** that exposes endpoints for integration with the `ui-service` or other systems.

Before building, choose the desired execution mode and adjust the `Dockerfile` accordingly.

#### 2.2.1 Command-line Interface

In the `customer-support-service` directory, open the `Dockerfile` and ensure the CLI service command is active while the Web API service command remains commented:

```dockerfile
# Start the CLI service.
# Uncomment this line only when running the service in CLI mode and ensure the Web API command is commented out.
CMD ["python", "app.py", "--cli"]

# Start the Web API service on port 8000 as the default behavior.
# Uncomment this line only when running the service in Web API mode and ensure the CLI command is commented out.
# CMD ["python", "app.py"]
```

Then build the container:

```bash
docker build -t customer-support-service .
```

This command builds a reproducible container image named `customer-support-service` using the local `Dockerfile`. All required Python dependencies are installed from `requirements.txt` file.

#### 2.2.2 Web API Interface

In the `customer-support-service` directory, open the `Dockerfile` and ensure the Web API service command is active while the CLI service command remains commented:

```dockerfile
# Start the CLI service.
# Uncomment this line only when running the service in CLI mode and ensure the Web API command is commented out.
# CMD ["python", "app.py", "--cli"]

# Start the Web API service on port 8000 as the default behavior.
# Uncomment this line only when running the service in Web API mode and ensure the CLI command is commented out.
CMD ["python", "app.py"]
```

Then build the container:

```bash
docker build -t customer-support-service .
```

This command builds a reproducible container image named `customer-support-service` using the local `Dockerfile`. All required Python dependencies are installed from `requirements.txt` file.

### 2.3 Run the Docker Container

After building, start the container using the command that matches your selected interface.

#### 2.3.1 Command-line Interface

```bash
docker run --rm -it --env-file ./.env customer-support-service --cli
```

Once running, the service launches an interactive customer support agent inside the container, enabling real-time conversational interactions directly from the terminal.

#### 2.3.2 Web API Interface

```bash
docker run --rm -it --env-file ./.env customer-support-service
docker run --rm -p 8000:8000 --env-file ./.env customer-support-service
```

Once running, the service launches an interactive customer support agent inside the container, enabling real-time conversational interactions through API requests. The FastAPI server becomes available on `http://localhost:8000`, ready to serve requests.

## 💻 3. Usage

The service is built to operate as an interactive console-based and API-integrated customer support agent. When the services starts, it prints a fixed welcome message:

```
Welcome to EcoMarket’s Customer Support Agent
```

From that point, the conversation is managed by the agentic reasoning workflow, which orchestrates dialogue and decision-making through data-grounded retrieval and validation. The agent supports two primary interaction flows:

- **Order Status Inquiries:** Provides structured details including tracking ID, items in the order, carrier, estimated delivery date (ETA), and delivery status.
- **Product Return Guidance:** Validates product eligibility and outlines next steps based on the business rules defined in the Returns Policy and Frequently Asked Questions documents.

Each response from the model is parsed and validated being displayed to the user. This guarantees structural integrity, consistent fallbacks, and predictable behavior throughout the interaction.

The screenshot below presents an example of a live console-based session, where the agent assists the user through checking the status of an order and validates the eligibility of items for return:

![CLI Agent Evidence](./images/cli_agent_evidence.png)

Additionally, the following screenshot shows the agent integrated with the `ui-service`, demonstrating a full web-based conversational experience powered by the same agentic reasoning and validated responses:

![Web UI Agent Evidence](./images/ui_agent_evidence.png)

## 📂 4. Project Structure

The service directory is organized as follows:

```
📂 customer-support-service                # Application for interactive customer support agent
├── 📄 .env                                # Example environment configuration file
├── 📄 Dockerfile                          # Dockerfile for customer support service
├── 📄 README.md                           # Service documentation
├── 📄 agent.py                            # Agent module logic
├── 📄 app.py                              # Core application logic
├── 📄 rag.py                              # RAG module logic
├── 📄 requirements.txt                    # Python dependencies
├── 📂 data                                # Data assets
│   ├── 📄 faqs.md                         # Frequently asked questions document
│   ├── 📄 orders_db.json                  # Example customer orders dataset
│   ├── 📄 product_catalog_db.json         # Example product catalog dataset
│   └── 📄 returns_policy.md               # Returns policy document
├── 📂 images                              # Visual assets used in documentation
│   ├── 📄 cli_agent_evidence.png          # Evidence of agent execution in CLI mode
│   └── 📄 ui_agent_evidence.png           # Evidence of agent execution in Web API mode
├── 📂 prompts                             # Prompt templates and configuration
│   └── 📄 settings.toml                   # Prompt configuration and system rules
└── 📂 tests                               # Unit tests for customer support service
    ├── 📄 test_agent.py                   # Unit test suite for validating agent logic and behavior
    ├── 📄 test_customer_support.py        # Unit test suite for validating service logic and behavior
    └── 📄 test_rag.py                     # Unit test suite for validating RAG logic and retrieval accuracy
```

### 🤖 5. Agent Workflow

The agent operates through an agentic reasoning workflow built on a LangChain-based Retrieval-Augmented Generation (RAG) core. This deterministic workflow combines semantic retrieval, structured data validation, and controlled orchestration to produce factually grounded and policy-compliant responses.

The system integrates both structured and unstructured sources into a unified reasoning process:
- **Structured data:** Orders and Product Catalog databases used for tracking and return eligibility validation.
- **Unstructured data:** Returns Policy and FAQs documents providing procedural and policy context.

The agent follows a deterministic workflow of reasoning and validation steps:

1. **Order Identification:** Detects tracking IDs through pattern recognition and retrieves the corresponding order data from the Orders database.
2. **Contextual Retrieval:** Uses the Chroma vector index, built with LangChain and HuggingFace embeddings, to extract relevant information from the Returns Policy, Product Catalog, and FAQs.
3. **Return Eligibility Validation:** For each product in delivered orders, the agent calculates the number of days since delivery and, if within the allowed window, evaluates whether the item is perishable or belongs to a restricted category using information from the Product Catalog, Returns Policy, and FAQs. Only products meeting all eligibility conditions are marked as returnable, while those that do not qualify are identified as ineligible with a clear, data-grounded justification.
4. **Policy Reasoning:** Merges factual order data with policy rules to generate compliant recommendations or next steps for the user.
5. **Response Validation:** Each generated response is validated against the predefined JSON schema to ensure data integrity, factual accuracy, and consistent conversational behavior.

This agentic orchestration ensures that every output is explainable, verifiable, and aligned with both data and business rules.

## 🔄 6. CI/CD Integration

This service is automatically validated, built, and deployed through GitHub Actions using a single workflow:

- The pipeline defined in `.github/workflows/main_pipeline.yml` runs on every push to the `main` branch.
- It performs the following stages:
  1. Executes unit tests for the `customer-support-service`.
  2. Builds Docker images for both services and pushes them to Amazon ECR.
  3. Connects securely to the target AWS EC2 instance and deploys both services via Docker.
- During deployment, the workflow injects all required environment variables from the repository’s GitHub Secrets, ensuring secure and consistent configuration across environments. These include credentials, ports, hostnames, and service URLs required by both the backend and the UI.
  Examples: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`, `BACKEND_PORT`, `FRONTEND_PORT`, `OPENAI_API_KEY`, and `S3_BUCKET`.
- Both the `customer-support-service` and `ui-service` containers are built and deployed using the latest image tag from Amazon ECR, ensuring each deployment reflects the most recent validated build.
- The backend container runs as a FastAPI application on the configured backend port, exposing the `/health`, `/chat`, and `/reset` endpoints used by the frontend.
- Logs from the deployment process are printed to the CI console, and any failure triggers an automatic stop and cleanup of previous containers.

CI/CD workflow definition:  
- [`.github/workflows/main_pipeline.yml`](../.github/workflows/main_pipeline.yml)

## 📦 7. Notes

- All interactive sessions are executed inside the container and produce structured JSON envelopes that conform to the defined response contract. This guarantees traceability and stability as prompts and configurations evolve over time.
- Orders and returns data are provided from local reference files for controlled experimentation:
  - `orders_db.json` provides representative order records used for order status inquiries and delivery validation.
  - `product_catalog_db.json` defines product categories, perishable attributes, and return window durations used for eligibility calculations.
  - `returns_policy.md` outlines the official business rules governing return and exchange conditions.
  - `faqs.md` supplements the policy with common customer questions and procedural clarifications.
- The service is designed to operate as part of a broader ecosystem and can be extended or integrated with:
  - Enterprise order management systems for live order tracking and carrier updates.
  - Policy management platforms to synchronize the latest return and refund guidelines.
  - Frontend UIs or support consoles that deliver the conversational experience to end users across chat, email, or social channels.
- Interactive execution is deterministic within the JSON contract. All outputs are validated, and any parsing or validation failure triggers a safe fallback, ensuring predictable behavior even under error conditions.
- Operational and security considerations:
  - The application requires the environment variable `OPENAI_API_KEY` defined in a `.env` file. This key provides access to the OpenAI API and must be available at runtime to enable model interaction.
  - No secrets are embedded in the container image. Always provide credentials securely through environment variables.
  - The container runs as a non-root user to minimize risk exposure.
  - Data and prompt files should be mounted read-only in production environments.
- Comprehensive automated tests validate all functional layers of the service, covering agentic reasoning, service orchestration, and retrieval logic:
  - `tests/test_agent.py` validates the agent module’s reasoning integrity, ensuring it exposes the required public APIs, that session resets are idempotent, and that the canonical JSON envelope structure remains stable and serializable across versions.
  - `tests/test_customer_support.py` performs end-to-end validation of the customer support flow, verifying that example envelopes conform to the defined JSON contract, required keys, and allowed intents, while maintaining type safety and logical consistency across order status and return scenarios.
  - `tests/test_rag.py` ensures the reliability of the retrieval layer, confirming that truncation limits are respected, empty retrievals are handled gracefully, and data loaders for Orders, Product Catalog, Returns Policy, and FAQs return valid, correctly structured content.

Together, these safeguards guarantee that the system operates consistently, securely, and in full alignment with its agentic and data-driven design.

## 📬 8. Contact

- **Danny Martinez**
   - **Email**: danny.martinez@u.icesi.edu.co, stevenmartinez880@gmail.com