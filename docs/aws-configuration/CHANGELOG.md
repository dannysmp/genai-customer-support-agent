# Changelog

## 🆕 v1.0.0 – 2025-10-24

This is the first release of the **AWS Configuration Guide** for the customer support agent platform. It provides a production-ready, fully documented infrastructure setup aligned with modern MLOps practices and AWS security standards.

### Highlights

- **Cloud Infrastructure Blueprint:** Complete setup of cloud infrastructure using AWS services including S3, IAM, ECR, and EC2 to support CI/CD, secure model storage, and automated deployment.

- **S3-Based Asset Management:** Defines a modular folder structure within an S3 bucket to organize the knowledge base documents, orders and product catalog databases. This structure supports both runtime and CI validation processes.

- **Secure IAM Configuration:** Introduces three critical identity layers:
  - An IAM user (`github-mlops`) for GitHub Actions integration.
  - A scoped IAM policy (`S3FullAccessToCustomerSupportAgentAssets`) for secure S3 access.
  - An EC2 role (`customer-support-agent-mlops-ec2-role`) for runtime access to ECR and S3.

- **Docker-Enabled EC2 Runtime:** Guides the creation and provisioning of a production EC2 instance capable of hosting Docker containers for all services, with proper IAM role assignment, firewall configuration, and port exposure for services.

- **GitHub Secrets Integration:** Details all required GitHub repository secrets to enable secure authentication with AWS services, and environment-aware deployments via GitHub Actions workflows.

- **Developer-Ready Environment:** Instructions include system updates, Git and Docker installation, and SSH access configuration to fully prepare the EC2 instance for running the containerized platform.

### Structural and Conceptual Foundations

- **Modular and Reproducible Setup:** The document is organized into logical sections (S3, IAM, ECR, EC2, GitHub Secrets), each with precise steps to ensure repeatability and ease of implementation even for first-time AWS users.

- **Security by Design:** All configurations adopt AWS security best practices, including least-privilege IAM policies, restricted access to sensitive resources, and avoidance of long-lived credentials through encrypted GitHub secrets.

- **CI/CD Alignment:** All AWS configurations are aligned with the automated pipelines defined in `.github/workflows`, ensuring seamless GitHub-to-AWS integration during builds, tests, and deployments.