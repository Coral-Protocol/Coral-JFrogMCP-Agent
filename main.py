import urllib.parse
from dotenv import load_dotenv
import os, json, asyncio, traceback, platform, base64
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_tool_calling_agent, AgentExecutor
import logging
from langchain_core.tools import StructuredTool
from utils.agent_tools import build_and_upload_to_jfrog, BuildAndUploadArgs


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

async def create_agent(coral_tools, agent_tools):
    coral_tools_description = get_tools_description(coral_tools)
    agent_tools_description = get_tools_description(agent_tools)
    combined_tools = coral_tools + agent_tools
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are an JFrog agent interacting with the tools from Coral Server and your Agent Tools. Your task is managing and interacting with JFrog Artifactory repositories, providing comprehensive repository management, package information retrieval, and vulnerability assessment capabilities.

            Follow these steps in order:
            1. Call wait_for_mentions from coral tools (timeoutMs: 30000) to receive mentions from other agents.
            2. When you receive a mention, keep the thread ID and the sender ID.
            3. Analyze the content (instruction) of the message and check only from the list of your Agent Tools available for you to action.
            4. If the instruction contains a path for building and uploading a project: a. Call the build_and_upload_to_jfrog tool with the provided parameters:
               - project_path: Path to the project directory
               - target_file_path: Target path in the repository
               - repository: Repository name (required). Store the result and path information for future use.
               - if the operation was successful, use this information for subsequent JFrog operations
            6. Check the tool schema and make a plan in steps for the JFrog task you want to perform.
            7. Only call the Agent tools you need to perform for each step of the plan to complete the instruction in the content (Do not call any other tool/tools unnecessarily).
            8. If you have previously built artifacts:
               - Include the build artifacts path in your JFrog operations
               - Use the stored build information when uploading or managing artifacts
            9. Review if you have executed the instruction to the best of your ability and the tools. Make this your response as "answer".
            10. Use `send_message` from coral tools to send a message in the same thread ID to the sender Id you received the mention from, with content: "answer".
            11. If any error occurs, use `send_message` to send a message in the same thread ID to the sender Id you received the mention from, with content: "error".
            12. Always respond back to the sender agent even if you have no answer or error.
            13. Return to step 1 and continue waiting for new mentions.

            These are the list of coral tools: {coral_tools_description}
            These are the list of Agent tools: {agent_tools_description}"""
                ),
                ("placeholder", "{agent_scratchpad}")

    ])

    model = init_chat_model(
        model=os.getenv("MODEL_NAME", "gpt-4.1"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        api_key=os.getenv("MODEL_API_KEY"),
        temperature=os.getenv("MODEL_TEMPERATURE", "0.1"),
        max_tokens=os.getenv("MODEL_MAX_TOKENS", "8000"),
        base_url=os.getenv("MODEL_BASE_URL", None)
    )
    agent = create_tool_calling_agent(model, combined_tools, prompt)
    return AgentExecutor(agent=agent, tools=combined_tools, verbose=True, handle_parsing_errors=True)

async def main():

    
    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", None)
    if runtime is None:
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


    timeout = os.getenv("TIMEOUT_MS", 300)
    client = MultiServerMCPClient(
        connections={
            "coral": {
                "transport": "sse",
                "url": CORAL_SERVER_URL,
                "timeout": timeout,
                "sse_read_timeout": timeout,
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
        name="build_and_upload_to_jfrog",
        coroutine=build_and_upload_to_jfrog,
        description="Builds a Python project using uv and uploads the resulting artifacts to JFrog Artifactory. "
                    "Supports cross-platform deployment with automatic platform detection. "
                    "Returns a success message with the location of uploaded artifacts or an error message if either build or upload fails.",
        args_schema=BuildAndUploadArgs,
        ),
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

    valid_tools_dict = {tool.name: tool for tool in valid_tools}

    result1 = await valid_tools_dict['jfrog_execute_aql_query'].ainvoke({
        "query": 'items.find({"repo":"coral-test","type":"file"}).include("name","path","repo")'
    })

    result2 = await valid_tools_dict['jfrog_get_artifacts_summary'].ainvoke({
        "paths": ["coral-test/python-packages/coral_coding_agent-0.1.0-py3-none-any.whl"]
    })

    logger.info(f"JFrog agent invocation result: {result1}"
                f"\nJFrog artifacts summary: {result2}")

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