## [JFrog MCP Agent](https://github.com/Coral-Protocol/Coralized-JFrog-MCP)
 
JFrog MCP Agent is a specialized agent for managing and interacting with JFrog Artifactory repositories, providing comprehensive repository management, package information retrieval, and vulnerability assessment capabilities through the Coral Protocol ecosystem.

## Responsibility
JFrog MCP Agent acts as the primary interface for JFrog Artifactory management within multi-agent workflows. It handles repository creation and configuration, package vulnerability analysis, build management, cluster monitoring, and permission management, enabling seamless integration of JFrog services into automated DevOps pipelines.

## Details
- **Framework**: LangChain
- **Tools used**: JFrog MCP Tools, Coral MCP Tools
- **AI model**: GPT-4o, supports configurable LLM providers
- **Date added**: June 30, 2025
- **License**: MIT

## Setup the Agent

### 1. Clone & Install Dependencies

<details>  

```bash
# In a new terminal clone the repository:
git clone https://github.com/Coral-Protocol/Coral-JFrogMCP-Agent.git

# Navigate to the project directory:
cd Coral-JFrogMCP-Agent

# Install `uv`:
pip install uv

# Install dependencies from `pyproject.toml` using `uv`:
uv sync
```

</details>

### 2. Configure Environment Variables

Get the required credentials:
- [OpenAI API Key](https://platform.openai.com/api-keys) or other LLM provider
- [JFrog Access Token](https://jfrog.com/help/r/jfrog-platform-administration-documentation/access-tokens)

<details>

```bash
# Create .env file in project root
cp -r .env_sample .env
```

Required environment variables:
- `MODEL_API_KEY`: Your LLM provider API key
- `MODEL_NAME`: LLM model name
- `MODEL_PROVIDER`: LLM provider
- `CORAL_SSE_URL`: Coral server SSE endpoint URL
- `CORAL_AGENT_ID`: Your Coral agent identifier
- `JFROG_ACCESS_TOKEN`: JFrog platform access token
- `JFROG_URL`: Your JFrog instance URL (e.g., https://mycompany.jfrog.io)

Optional environment variables:
- `MODEL_TEMPERATURE`: Model temperature
- `MODEL_MAX_TOKENS`: Max tokens

</details>

## Run the Agent

You can run in either of the below modes to get your system running.  

- The Executable Model is part of the Coral Protocol Orchestrator which works with [Coral Studio UI](https://github.com/Coral-Protocol/coral-studio).  
- The Dev Mode allows the Coral Server and all agents to be separately running on each terminal without UI support.  

### 1. Executable Mode

Checkout: [How to Build a Multi-Agent System with Awesome Open Source Agents using Coral Protocol](https://github.com/Coral-Protocol/existing-agent-sessions-tutorial-private-temp) and update the file: `coral-server/src/main/resources/application.yaml` with the details below, then run the [Coral Server](https://github.com/Coral-Protocol/coral-server) and [Coral Studio UI](https://github.com/Coral-Protocol/coral-studio). You do not need to set up the `.env` in the project directory for running in this mode; it will be captured through the variables below.

<details>

For Linux or MAC:

```bash

registry:
    # ... your other agents
  jfrog-mcp:
    options:
      - name: "MODEL_API_KEY"
        type: "string"
        description: "API key for the model provider"
      - name: "MODEL_NAME"
        type: "string"
        description: "What model to use (e.g 'gpt-4o')"
        default: "gpt-4.1-mini"
      - name: "MODEL_PROVIDER"
        type: "string"
        description: "What model provider to use (e.g 'openai', 'groq', etc)"
        default: "openai"
      - name: "MODEL_MAX_TOKENS"
        type: "string"
        description: "Max tokens to use"
        default: "8000"
      - name: "MODEL_TEMPERATURE"
        type: "string"
        description: "What model temperature to use"
        default: "0.3"
      - name: "JFROG_ACCESS_TOKEN"
        type: "string"
        description: "JFrog platform access token"
      - name: "JFROG_URL"
        type: "string"
        description: "JFrog instance URL (e.g., https://mycompany.jfrog.io)"

    runtime:
      type: "executable"
      command: ["bash", "-c", "<replace with path to this agent>/run_agent.sh jfrog-mcp_coral_agent.py"]
      environment:
        - option: "MODEL_API_KEY"
        - option: "MODEL_NAME"
        - option: "MODEL_PROVIDER"
        - option: "MODEL_MAX_TOKENS"
        - option: "MODEL_TEMPERATURE"
        - option: "JFROG_ACCESS_TOKEN"
        - option: "JFROG_URL"

```

For Windows, create a powershell command (run_agent.ps1) and run:

```bash
command: ["powershell","-ExecutionPolicy", "Bypass", "-File", "${PROJECT_DIR}/run_agent.ps1","jfrog-mcp_coral_agent.py"]
```

</details>

### 2. Dev Mode

Ensure that the [Coral Server](https://github.com/Coral-Protocol/coral-server) is running on your system and run below command in a separate terminal.

<details>

```bash
# Run the agent using `uv`:
uv run main.py
```
</details>

## Capabilities

The JFrog MCP Agent provides comprehensive JFrog Artifactory management capabilities:

### Repository Management
- Create and configure local, remote, and virtual repositories
- List and filter repositories by type, package type, and project
- Set properties on folders with recursive options

### Package & Vulnerability Management
- Retrieve package information from public repositories
- Get package versions and vulnerability assessments
- Check package curation status for security compliance
- Query specific vulnerability details (CVE information)

### Build & Deployment
- List and manage builds in the JFrog platform
- Get specific build details and metadata
- Monitor build status and deployment information

### Infrastructure Monitoring
- List and monitor runtime clusters
- Get cluster-specific details and status
- Monitor running container images with security status

### Project & Permission Management
- Create and manage projects with storage quotas
- Configure permission targets and access controls
- Manage user and group permissions for resources

### Advanced Querying
- Execute Artifactory Query Language (AQL) queries
- Search for artifacts, builds, and other entities
- Filter and sort results with complex criteria

## Example

<details>

```bash
# Input from orchestrating agent:
"Create a new Maven local repository called 'my-maven-local' and set it up for the development environment"

# JFrog Agent Response:
Successfully created Maven local repository 'my-maven-local'
Repository Details:
   - Type: Local
   - Package Type: Maven
   - Environment: development
   - Status: Active
   
Repository is ready for artifact storage and retrieval.

```
</details>

## Creator Details
- **Name**: Mustafa Khan
- **Affiliation**: Coral Protocol
- **Contact**: [Discord](https://discord.com/invite/Xjm892dtt3)
