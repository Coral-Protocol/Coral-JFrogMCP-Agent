import urllib.parse
from dotenv import load_dotenv
import os, json, asyncio, traceback, platform, base64
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_tool_calling_agent, AgentExecutor
import logging
from langchain_core.tools import StructuredTool


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field
class BuildToolArgs(BaseModel):
    file_path: str = Field(description="Path to the project directory containing pyproject.toml or setup.py")

class UploadToJFrogArgs(BaseModel):
    source_file_path: str = Field(description="Path to the source file to upload")
    target_file_path: str = Field(description="Target path in JFrog repository (e.g., 'python-packages/my-package.tar.gz')")
    repository: str = Field(description="JFrog repository name")


def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )


async def python_build_tool(file_path: str) -> str:
    """
    Build a Python project using uv at the specified file_path.
    
    Args:
        file_path (str): Path to the project directory containing pyproject.toml or setup.py.
    
    Returns:
        str: Success message or error message if the build fails.
    """
    try:
        # Validate file_path
        if not os.path.isdir(file_path):
            error = f"Directory does not exist: {file_path}"
            logger.error(error)
            return error
        
        # Check for pyproject.toml or setup.py
        if not (os.path.exists(os.path.join(file_path, "pyproject.toml")) or 
                os.path.exists(os.path.join(file_path, "setup.py"))):
            error = f"No pyproject.toml or setup.py found in {file_path}"
            logger.error(error)
            return error
        
        # Run uv build in the specified directory
        proc = await asyncio.create_subprocess_exec(
            "uv", "build", file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=file_path
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            success_msg = f"Successfully built project at {file_path}. Artifacts in {os.path.join(file_path, 'dist')}"
            logger.info(success_msg)
            return success_msg
        else:
            error = f"Build failed: {stderr.decode()}"
            logger.error(error)
            return error
            
    except Exception as e:
        error = f"Error occurred while processing python build tool: {str(e)}"
        logger.error(error)
        traceback.print_exc()
        return error

async def upload_to_jfrog(source_file_path: str, target_file_path: str, repository: str) -> str:
    """
    Upload a file to JFrog Artifactory using curl (Linux/WSL) or PowerShell (Windows).
    
    Args:
        source_file_path (str): Path to the source file to upload
        target_file_path (str): Target path in JFrog repository
        repository (str): JFrog repository name
    
    Returns:
        str: Success message or error message if the upload fails.
    """
    try:
        # Validate source file exists
        if not os.path.exists(source_file_path):
            error = f"Source file does not exist: {source_file_path}"
            logger.error(error)
            return error
        
        # Get email from environment variable
        email = os.getenv("JFROG_EMAIL", "k230912@nu.edu.pk")
        token = os.getenv("JFROG_TOKEN")
        jfrog_url = os.getenv("JFROG_URL")
        
        # Validate required environment variables
        if not token:
            error = "JFROG_TOKEN environment variable is not set"
            logger.error(error)
            return error
        
        if not jfrog_url:
            error = "JFROG_URL environment variable is not set"
            logger.error(error)
            return error
        
        # Log the upload attempt for debugging
        logger.info(f"Attempting to upload {source_file_path} to repository '{repository}' at path '{target_file_path}'")
        logger.info(f"JFrog URL: {jfrog_url}")
        logger.info(f"Email: {email}")
        
        # Determine platform and execute appropriate command
        system = platform.system().lower()
        
        if system in ["linux", "darwin"]:
            # Linux/WSL - use curl command
            curl_cmd = [
                "curl", f"-u{email}:" + token,
                "-T", source_file_path,
                f"{jfrog_url}/artifactory/{repository}/{target_file_path}"
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *curl_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                success_msg = f"Successfully uploaded {source_file_path} to {jfrog_url}/artifactory/{repository}/{target_file_path}"
                logger.info(success_msg)
                return success_msg
            else:
                error = f"Upload failed: {stderr.decode()}"
                logger.error(error)
                return error
                
        elif system == "windows":
            # Windows - use PowerShell
            auth_string = f"{email}:{token}"
            base64_auth = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
            
            powershell_cmd = [
                "powershell", "-Command",
                f'$base64AuthInfo = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("{auth_string}")); '
                f'Invoke-WebRequest -Uri "{jfrog_url}/artifactory/{repository}/{target_file_path}" -Headers @{{Authorization=("Basic {{0}}" -f $base64AuthInfo)}} -Method PUT -InFile "{source_file_path}"'
            ]
            
            # Log the PowerShell command for debugging
            logger.info(f"Executing PowerShell command: {' '.join(powershell_cmd)}")
            
            proc = await asyncio.create_subprocess_exec(
                *powershell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                success_msg = f"Successfully uploaded {source_file_path} to {jfrog_url}/artifactory/{repository}/{target_file_path}"
                logger.info(success_msg)
                return success_msg
            else:
                stdout_output = stdout.decode() if stdout else ""
                stderr_output = stderr.decode() if stderr else ""
                error = f"Upload failed: {stderr_output}\nStdout: {stdout_output}"
                logger.error(error)
                return error
        else:
            error = f"Unsupported platform: {system}"
            logger.error(error)
            return error
            
    except Exception as e:
        error = f"Error occurred while uploading to JFrog: {str(e)}"
        logger.error(error)
        traceback.print_exc()
        return error


async def create_agent(coral_tools, agent_tools):
    coral_tools_description = get_tools_description(coral_tools)
    agent_tools_description = get_tools_description(agent_tools)
    combined_tools = coral_tools + agent_tools
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are an JFrog agent interacting with the tools from Coral Server and your Agent Tools. 
            Your task is managing and interacting with JFrog Artifactory repositories, providing comprehensive repository management, package information retrieval, and vulnerability assessment capabilities.

            Follow these steps in order:
            1. Call wait_for_mentions from coral tools (timeoutMs: 30000) to receive mentions from other agents.
            2. When you receive a mention, keep the thread ID and the sender ID.
            3. Analyze the content (instruction) of the message and check only from the list of your Agent Tools available for you to action.
            4. If the instruction contains a path for building a project:
               a. Call the python_build_tool with the provided path
               b. Store the build result and path information for future use
               c. If the build was successful, use this information for subsequent JFrog operations
            5. If the instruction involves uploading files to JFrog Artifactory:
               a. Use the upload_to_jfrog tool with the required parameters:
                  - source_file_path: Path to the file to upload
                  - target_file_path: Target path in the repository
                  - repository: Repository name (required)
               b. The tool automatically uses environment variables for authentication and JFrog URL
               c. Handle upload results and report back
            6. Check the tool schema and make a plan in steps for the JFrog task you want to perform.
            7. Only call the Agent tools you need to perform for each step of the plan to complete the instruction in the content(Do not call any other tool/tools unnecessarily).
            8. If you have previously built artifacts:
               a. Include the build artifacts path in your JFrog operations
               b. Use the stored build information when uploading or managing artifacts
            9. Review if you have executed the instruction to the best of your ability and the tools. Make this your response as "answer".
            10. Use `send_message` from coral tools to send a message in the same thread ID to the sender Id you received the mention from, with content: "answer".
            11. If any error occurs, use `send_message` to send a message in the same thread ID to the sender Id you received the mention from, with content: "error".
            12. Always respond back to the sender agent even if you have no answer or error.
            13. Return to step 1 and continue monitoring for new mentions.

            These are the list of coral tools: {coral_tools_description}
            These are the list of Agent tools: {agent_tools_description}"""
                ),
                ("placeholder", "{agent_scratchpad}")

    ])

    model = init_chat_model(
        model=os.getenv("MODEL_NAME", "gpt-4.1"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        api_key=os.getenv("API_KEY"),
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0.3")),
        max_tokens=int(os.getenv("MODEL_TOKEN", "4000"))
    )
    agent = create_tool_calling_agent(model, combined_tools, prompt)
    return AgentExecutor(agent=agent, tools=combined_tools, verbose=True)

async def main():

    
    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", "devmode")
    if runtime == "docker" or runtime == "executable":
        base_url = os.getenv("CORAL_SSE_URL")
        agentID = os.getenv("CORAL_AGENT_ID")
    else:
        load_dotenv()
        base_url = os.getenv("CORAL_SSE_URL")
        agentID = os.getenv("CORAL_AGENT_ID")

    coral_params = {
        "agentId": agentID,
        "agentDescription": "JFrog MCP Agent is a specialized agent for managing and interacting with JFrog Artifactory repositories, providing comprehensive repository management, package information retrieval, and vulnerability assessment capabilities"
    }

    query_string = urllib.parse.urlencode(coral_params)

    CORAL_SERVER_URL = f"{base_url}?{query_string}"
    logger.info(f"Connecting to Coral Server: {CORAL_SERVER_URL}")

    client = MultiServerMCPClient(
        connections={
            "coral": {
                "transport": "sse",
                "url": CORAL_SERVER_URL,
                "timeout": 600,
                "sse_read_timeout": 600,
            },
            "MCP-JFrog": {
                "transport": "stdio",
                "command": 'npm',
                "args": ['exec', '-y', 'github:jfrog/mcp-jfrog'],
                "env": {
                    "JFROG_ACCESS_TOKEN": os.getenv("JFROG_ACCESS_TOKEN"),
                    "JFROG_URL": os.getenv("JFROG_URL")
                }
            }
        }
    )
    logger.info("Coral Server and JFrog MCP Connection Established")

    coral_tools = await client.get_tools(server_name="coral")
    logger.info(f"Coral tools count: {len(coral_tools)}")
    
    mcp_tools = await client.get_tools(server_name="MCP-JFrog")
    logger.info(f"JFrog tools count: {len(mcp_tools)}")

    agent_tools = mcp_tools + [
        StructuredTool.from_function(
            name="python_build_tool",
            coroutine=python_build_tool,
            description="Builds a Python project at the specified file_path using uv, creating distribution packages (source distribution and wheel). " \
            "Returns a success message with the location of build artifacts or an error message if the build fails.",
            args_schema=BuildToolArgs
        ),
        StructuredTool.from_function(
            name="upload_to_jfrog",
            coroutine=upload_to_jfrog,
            description="Uploads a file to JFrog Artifactory repository using curl (Linux/WSL) or PowerShell (Windows). " \
            "Supports cross-platform deployment with automatic platform detection. " \
            "Returns a success message or error message if the upload fails.",
            args_schema=UploadToJFrogArgs
        )
    ]

    problematic_tools = []
    valid_tools = []
    
    for tool in agent_tools:
        try:
            if hasattr(tool, 'args'):
                def find_refs(obj):
                    refs = []
                    if isinstance(obj, dict):
                        if '$ref' in obj:
                            refs.append(obj['$ref'])
                        for v in obj.values():
                            refs.extend(find_refs(v))
                    elif isinstance(obj, list):
                        for item in obj:
                            refs.extend(find_refs(item))
                    return refs
                
                refs = find_refs(tool.args)
                if refs:
                    problematic_tools.append((tool.name, refs))
                else:
                    valid_tools.append(tool)
            else:
                valid_tools.append(tool)
        except Exception as e:
            problematic_tools.append((tool.name, str(e)))
    
    # Log problematic tools for debugging
    # if problematic_tools:
    #     logger.warning(f"Found {len(problematic_tools)} problematic tools:")
        # for tool_name, issue in problematic_tools:
        #     logger.warning(f"  - {tool_name}: {issue}")
    logger.info(f"Using {len(valid_tools)} valid tools out of {len(agent_tools)} total tools")
    
    agent_executor = await create_agent(coral_tools, valid_tools)

    while True:
        try:
            logger.info("Starting new JFrog agent invocation")
            await agent_executor.ainvoke({"agent_scratchpad": []})
            logger.info("Completed JFrog agent invocation, restarting loop")
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in JFrog agent loop: {str(e)}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())