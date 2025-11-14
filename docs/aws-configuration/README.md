# AWS Configuration

This document describes all required AWS configurations to support the CI/CD pipeline and end-to-end deployment of the Customer Support Agent platform. These instructions are tailored for first-time AWS users and guide the integration of GitHub Actions with key AWS services, including Docker image publishing, and full-service deployment.

The platform relies on AWS S3 for hosting the knowledge base documents, orders and product catalog databases that power the Retrieval-Augmented Generation (RAG) layer.
Docker images for each service are versioned and published to AWS Elastic Container Registry (ECR), while both the customer support agent and user interface are deployed as containerized services on an AWS EC2 instance, ensuring isolated, containerized execution.

## 🪣 1. S3 Bucket

The bucket `genai-customer-support-agent` serves as the centralized storage location for the knowledge base documents, orders and product catalog databases used by the platform.

**Steps to Create:**

1. Go to the [Amazon S3 Console](https://s3.console.aws.amazon.com/s3).
2. Click **Create bucket**.
3. Set the following configuration:
   - **Bucket name**: `genai-customer-support-agent`
   - **Region**: `us-east-1` (N. Virginia)
4. In **Object Ownership**:
   - Select: **ACLs disabled (recommended)**
   - Confirm **Bucket owner enforced** is selected (default)
5. In **Block Public Access settings**:
   - Keep **all four options enabled** (recommended for security)
6. Leave **versioning** disabled *(optional – can be enabled later if data versioning is required)*
7. Leave all other options at their default values and click **Create bucket**.

**Create Folders in S3:**

After the bucket is created, define a clear folder structure to organize project assets effectively.

1. Open the newly created bucket.
2. Click **Create folder**.
3. Create the following folders to organize application data:

```
🪣 genai-customer-support-agent
├── 📂 catalogs
│ └── 📄 product_catalog_db.json
├── 📂 faqs
│ └── 📄 faqs.md
├── 📂 orders
│ └── 📄 orders_db.json
└── 📂 policies
  └── 📄 returns_policy.md
```

- `catalogs`: Contains the product catalog database to retrieve product details.
- `faqs`: Stores the FAQ document with common customer inquiries.
- `orders`: Contains the orders database used to retrieve order details.
- `policies`: Stores the returns policy document defining business rules for returns.

This folder structure ensures modular organization of artifacts and supports both CI workflow and runtime environment.

**Upload Files:**

Upload the required resources into their respective folders:

- The product catalog database to the `catalogs/` folder.
- The FAQ document to the `faqs/` folder.
- The orders database to the `orders/` folder.
- The returns policy document to the `policies/` folder.

This storage setup ensures consistent asset retrieval across builds and supports reliability during service execution.

## 🛡️ 2. IAM Configuration

Identity and Access Management (IAM) is a core AWS service that enables fine-grained access control across cloud resources. In this project, IAM is used to securely connect GitHub Actions with AWS services and to grant runtime permissions to EC2 instances hosting the deployed services.

This section outlines the IAM configuration required to support the MLOps pipeline:

- An **IAM user** (`github-mlops`) that enables GitHub Actions to programmatically access AWS resources for building and deploying services.
- A **custom IAM policy** (`S3FullAccessToCustomerSupportAgentAssets`) that grants scoped access to the project's S3 bucket.
- An **IAM role** (`customer-support-agent-mlops-ec2-role`) that allows EC2 instances to pull Docker images from Amazon ECR and access the S3 bucket to retrieve the knowledge base documents, orders and product catalog databases required during runtime.

Together, these IAM entities ensure that both the automated workflows and runtime services operate securely, following the principle of least privilege.

### 2.1 IAM User for GitHub Actions

The IAM user `github-mlops` is created to enable secure programmatic access from GitHub Actions to AWS services such as S3, ECR, and EC2. This user is configured with the minimum set of permissions required to perform deployment operations across the CI/CD pipeline.

**Steps to Create:**

1. Go to the [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. In the left sidebar, click **Users**, then click **Create user**.
3. Set the **User name** to: `github-mlops`, then click **Next**.
4. Under **Set permissions → Permissions options**, select **Attach policies directly**.
5. In the list of AWS managed **Permissions policies**, check the following and click **Next**:
   - `AmazonEC2FullAccess`
   - `AmazonS3FullAccess`
   - `AmazonEC2ContainerRegistryFullAccess`
6. Skip the **Tags** section.
7. Review your selections and click **Create user**.

At this point, the user will be created without programmatic access keys. To enable GitHub Actions to interact with AWS services, you must manually generate a new set of credentials as described below.

1. In the IAM console, click on the newly created user `github-mlops`.
2. Go to the **Security credentials** tab.
3. Scroll down to the **Access keys** section.
4. Click **Create access key**.
5. Choose the use case: **Command Line Interface (CLI)** and click **Next**.
6. Optionally add a **Description tag value** (e.g., *GitHub Actions CI/CD pipeline*).
7. Click **Create access key**.

After the access key is created, you will be presented with the following credentials:

- **Access Key ID**
- **Secret Access Key**

> ⚠️ **Important**: These values will be shown only once. You must download them using the **Download .csv file** button or copy them manually and store them in a secure location (e.g., a credential manager or encrypted vault).

Once the access key has been created, proceed to configure these credentials as GitHub repository secrets.

### 2.2 IAM Policy for S3 Bucket

To grant EC2 instances secure and scoped access to the project-specific S3 bucket (`genai-customer-support-agent`), a custom policy named `S3FullAccessToCustomerSupportAgentAssets` must be created. This policy enables access to the knowledge base documents, orders and product catalog databases.

**Steps to Create:**

1. Go to the [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. In the left sidebar, click **Policies**, then click **Create policy**.
3. In **Policy editor**, switch to the **JSON** tab and paste the following content:

```json
{
   "Version": "2012-10-17",
   "Statement": [
      {
         "Sid": "S3AccessToCustomerSupportAgentAssets",
         "Effect": "Allow",
         "Action": [
            "s3:GetObject",
            "s3:ListBucket"
         ],
         "Resource": [
            "arn:aws:s3:::genai-customer-support-agent",
            "arn:aws:s3:::genai-customer-support-agent/*"
         ]
      }
   ]
}
```

4. Click **Next**.
5. Set the **Policy name** to `S3FullAccessToCustomerSupportAgentAssets`.
6. Add a **Description** (optional but recommended) for the policy (e.g., *Grants full access to the genai-customer-support-agent S3 bucket.*).
7. Click **Create policy**.

This policy will be attached to the EC2 role described in the next section.

### 2.3 IAM Role for EC2 Instance

The IAM role `customer-support-agent-mlops-ec2-role` is created to grant EC2 instances the necessary permissions to operate within the MLOps pipeline. Specifically, it allows instances to pull Docker images from Amazon ECR and to interact with the project’s S3 bucket, including reading the knowledge base documents, orders and product catalog databases. Assigning this role ensures that all runtime services deployed on EC2 can securely access the data and containers required for correct operation.

**Steps to Create:**

1. Go to the [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. In the left sidebar, click **Roles**, then click **Create role**.
3. Under **Trusted entity type**, select: `AWS service`.
4. Under **Service or use case**, select: `EC2`.
4. In **Use case**, choose: `EC2`, then click **Next**.
5. In the **Permissions policies** section, attach the following:
   - `AmazonEC2ContainerRegistryReadOnly`
   - `S3FullAccessToCustomerSupportAgentAssets` (the custom policy created in section 2.2)
6. Click **Next**.
7. Set the **Role name** to `customer-support-agent-mlops-ec2-role`.
8. Add a **Description** for the role (e.g., *Grants EC2 permissions to access ECR and S3 for MLOps deployments via GitHub Actions.*).
9. Click **Create role**.

> ⚠️ **Important**: This role will be assigned to the EC2 instance during creation. It enables containerized services running on the instance to securely access model files and write predictions to S3, as well as pull the latest Docker images from Amazon ECR.

### 2.4 Long-Term Security Considerations

While using an IAM user with access keys is acceptable for initial setups, **it is strongly recommended to adopt stricter security practices** for long-term, production-grade workflows:

- For production environments, consider creating scoped IAM roles instead of full-access policies.
- To eliminate long-lived credentials, **use GitHub Actions using OIDC (OpenID Connect)** with a trusted role for federation.
- Limit permissions to only those needed, following the principle of least privilege.

> ⚠️ **Important**: These configurations align with AWS security best practices to minimize risk in automated CI/CD deployments. Never hardcode credentials or expose them in version control. Always use encrypted secrets and IAM roles to manage access securely whenever possible.

## 📦 3. ECR Repository

The Elastic Container Registry (ECR) repositories serve as the centralized location for storing versioned Docker images for each service within the platform (`customer-support-service` and `ui-service`). These images are built and pushed automatically by the GitHub Actions pipeline as part of the CI/CD process.

These repositories enable decoupling of image build and deployment phases, ensure reproducibility, and facilitate efficient rollbacks or redeployments.

The project requires the following Amazon ECR repositories to be created.

| Service                        | Repository Name                                             |
|--------------------------------|-------------------------------------------------------------|
| Customer Support Service       | `customer-support-agent-mlops/customer-support-service`     |
| UI Service                     | `customer-support-agent-mlops/ui-service`                   |

**Steps to Create:**

1. Go to the [Amazon ECR Console](https://console.aws.amazon.com/ecr).
2. Click **Create repository**.
3. Enter the **Repository name** as shown above for each service.
4. Under **Image tag mutability**, choose `Mutable` (recommended for CI/CD workflows that overwrite tags like `latest`).
5. Under **Encryption settings**, leave the default option selected: `AES-256` (standard encryption).
6. Leave all other settings at their default values.
7. Click **Create**.

> ⚠️ **Important**: These steps must be repeated **once per service** to create the repositories.

Once created, take note of the full **Repository URIs** as they will be required for authenticating and pushing images from GitHub Actions (e.g., 
`051922710546.dkr.ecr.us-east-1.amazonaws.com/customer-support-agent-mlops/customer-support-service`).

These URIs will be added to the repository's GitHub secrets configuration for each service:

- `ECR_CUSTOMER_SUPPORT_SERVICE_REPOSITORY` for the `customer-support-service`
- `ECR_UI_SERVICE_REPOSITORY` for the `ui-service`

## 💻 4. EC2 Instance

The EC2 instance `customer-support-agent-instance` is responsible for hosting the Docker containers for both `customer-support-service` and `ui-service`.

**Steps to Create:**

1. Go to the [Amazon EC2 Console](https://console.aws.amazon.com/ec2).
2. Click **Launch Instance**.
3. Name the instance: `customer-support-agent-instance`.
4. In **Application and OS Images (Amazon Machine Image)**, select: `Amazon Linux 2023 AMI, x86_64` (eligible for AWS Free Tier).
5. Set the **Instance Type** to: `t3.medium` (recommended, 4 GiB RAM).
6. In **Key pair (login)**, choose **Create new key pair**:
   - Name the key pair: `customer-support-agent-key-pair`
   - Key pair type: `RSA`
   - Private key file format: `.pem`
   - Click **Create key pair** and securely store the downloaded `.pem` file.
7. Under **Network settings**:
   - In **Firewall (security groups)**, select **Create security group** to define custom access rules for this instance. Alternatively, choose **Select existing security group** if one with the appropriate rules already exists.
   - Check **Allow SSH traffic from →** `Anywhere (0.0.0.0/0)` to facilitate collaborative development. In production environments, access should be restricted to specific IPs or managed via a bastion host or VPN to prevent unauthorized access.
   - Check **Allow HTTP traffic from the internet**
   - Check **Allow HTTPS traffic from the internet** (if HTTPS is required)
8. In **Advanced details → IAM instance profile**, select the IAM role `customer-support-agent-mlops-ec2-role`. This role enables the instance to pull Docker images from ECR and access the project’s S3 bucket during runtime.
9. Leave the rest of the settings as default and click **Launch Instance**.

Once the instance has been launched, custom ports must be explicitly added to the security group’s inbound rules to allow external access to the containerized services.

**Open Additional Ports:**

1. In the EC2 console, click on the newly created instance `customer-support-agent-instance`.
2. In the **Security** tab, click the associated **Security group ID**.
3. In the **Inbound rules** tab and click **Edit inbound rules**.
4. Add the following custom TCP rules:
   - **Type**: Custom TCP — **Port range**: `8000` — **Source**: `0.0.0.0/0` - **Description** (optional): *Allow customer-support-service* → (for customer-support-service)
   - **Type**: Custom TCP — **Port range**: `8501` — **Source**: `0.0.0.0/0` - **Description** (optional): *Allow ui-service* → (for ui-service)
5. Click **Save rules** to apply the changes.

This ensures external connectivity to the deployed services through the designated ports.

> ⚠️ **Important**: While `t2.micro` and `t3.small` instances are eligible for the AWS Free Tier or offer lower-cost options, they do not provide sufficient memory or CPU resources to reliably host multiple containers. It is recommended to use an instance type such as `t3.medium` or larger to ensure stable and consistent runtime performance.

Once the instance is running, the following values are required for your GitHub Secrets:

- **`EC2_HOST`**: Copy the Public IP or Public DNS of the EC2 instance.
- **`EC2_USER`**: Use the appropriate SSH username for the selected AMI (e.g., `ec2-user` for `Amazon Linux 2023 AMI`).
- **`EC2_SSH_KEY`**: Use the full content of the `.pem` private key file generated during the key pair creation.

> ⚠️ **Important**: Never share your private key file (`.pem`) or commit it to source control. Use `.gitignore` to exclude any key files from versioning.

### 4.1 SSH Access

After the instance is running, ensure proper permissions are set for the private key file:

```bash
chmod 400 customer-support-agent-key-pair.pem
```

You can then initiate an SSH connection using the instance’s public IP address:

```bash
ssh -i customer-support-agent-key-pair.pem ec2-user@<EC2-PUBLIC-IP>
```

### 4.2 Initial Setup on EC2

The following steps install and configure the tools required for running the application containers. Execute each step in sequence after logging into your EC2 instance.

#### 4.2.1. Update the System

Ensure that all system packages are up to date:

```bash
sudo yum update -y
```

This ensures compatibility and security by applying the latest updates provided by Amazon Linux.

#### 4.2.2. Install Git

Git is required for cloning the application repository:

```bash
sudo yum install git -y
```

Verify that Git is correctly installed:

```bash
git --version
```

#### 4.2.3. Install Docker

Docker is used to build and run the containerized services:

```bash
sudo yum install docker -y

sudo systemctl start docker

sudo systemctl enable docker
```

To allow the default `ec2-user` to run Docker commands without `sudo`, add it to the Docker group:

```bash
sudo usermod -aG docker ec2-user
```

> ⚠️ **Important**: After modifying group permissions, you must log out and reconnect for the changes to take effect:

```bash
exit

ssh -i customer-support-agent-key-pair.pem ec2-user@<EC2-PUBLIC-IP>
```

With the EC2 environment fully provisioned and all essential tools installed, the instance is now ready to receive deployments from GitHub Actions. Each service is deployed as an independent Docker container during the CI/CD process.

## 🔐 5. GitHub Secrets Configuration

To enable secure integration between GitHub Actions and your AWS infrastructure, define the following repository-level secrets. These secrets ensure that all pipeline operations, from pulling models to deploying containers, are authenticated and environment-aware.

**Steps to Create:**

1. In your GitHub repository, navigate to: **Settings → Secrets and variables → Actions**.
2. Under the **Secrets** tab, click **New repository secret** and create each of the following key-value pairs:

| Secret Name                                     | Value (from AWS)                                                |
|-------------------------------------------------|-----------------------------------------------------------------|
| `AWS_ACCESS_KEY_ID`                             | Access Key ID from IAM user                                     |
| `AWS_REGION`                                    | `us-east-1`                                                     |
| `AWS_SECRET_ACCESS_KEY`                         | Secret Access Key from IAM user                                 |
| `BACKEND_PORT`                                  | `8000`                                                          |
| `EC2_HOST`                                      | Public IP or DNS of the EC2 instance                            |
| `EC2_SSH_KEY`                                   | Full content of the `.pem` private key from the EC2 key pair    |
| `EC2_USER`                                      | SSH username of the EC2 instance (e.g., `ec2-user`)             |
| `ECR_CUSTOMER_SUPPORT_SERVICE_REPOSITORY`       | Full URI of ECR repository for `customer-support-service`       |
| `ECR_UI_SERVICE_REPOSITORY`                     | Full URI of ECR repository for `ui-service`                     |
| `FRONTEND_PORT`                                 | `8501`                                                          |
| `OPENAI_API_KEY`                                | API key for accessing OpenAI models                             |  
| `S3_BUCKET`                                     | `genai-customer-support-agent`                                  |

**Purpose of Each GitHub Secret:**

- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: Authenticate GitHub Actions with AWS.
- `AWS_REGION`: Specifies the AWS region where all infrastructure components are deployed (`us-east-1`).
- `BACKEND_PORT`: Defines the port of the `customer-support-service`.
- `EC2_HOST`: Target server where services will be deployed via SSH.
- `EC2_SSH_KEY`: Provides secure authentication for the SSH session from GitHub Actions.
- `EC2_USER`: Authorized SSH user to run Docker commands on the EC2 host.
- `ECR_CUSTOMER_SUPPORT_SERVICE_REPOSITORY`: URI to push the `customer-support-service` Docker image.
- `ECR_UI_SERVICE_REPOSITORY`: URI to push the `ui-service` Docker image.
- `FRONTEND_PORT`: Defines the port of the `ui-service`.
- `OPENAI_API_KEY`: Secure key used by the backend to access OpenAI’s API for natural language processing tasks.
- `S3_BUCKET`: Indicates the S3 bucket where the pipeline retrieves the knowledge base, orders and product catalog databases required by the services.

Once configured, these secrets will allow your GitHub Actions workflows to:

- Retrieve required data files from the S3 bucket during runtime.
- Build, tag, and publish Docker images to ECR.
- Deploy services to EC2 environment. 

> ⚠️ **Important**: All secrets must be defined in the same GitHub repository where the CI/CD workflows are defined. Do not commit any credential-related content to source control.

## 📬 6. Contact

- **Danny Martinez**
   - **Email**: danny.martinez@u.icesi.edu.co, stevenmartinez880@gmail.com