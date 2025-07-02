import urllib.parse
from dotenv import load_dotenv
import os, json, asyncio, traceback
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_tool_calling_agent, AgentExecutor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

base_url = os.getenv("CORAL_SSE_URL")
agentID = os.getenv("CORAL_AGENT_ID")

coral_params = {
    "agentId": agentID,
    "agentDescription": "I am an MCP-JFrog agent capable of managing and interacting with software repositories, including creating and configuring local, remote, and virtual repositories, setting properties on folders, listing repositories, builds, clusters, and environments, managing projects and permission targets, executing AQL queries, and retrieving package and vulnerability information within an Artifactory environment."
}

query_string = urllib.parse.urlencode(coral_params)

def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

async def create_agent(coral_tools, agent_tools):
    coral_tools_description = get_tools_description(coral_tools)
    agent_tools_description = get_tools_description(agent_tools)
    
    problematic_tools = []
    valid_tools = []
    
    for tool in coral_tools + agent_tools:
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
    if problematic_tools:
        logger.warning(f"Found {len(problematic_tools)} problematic tools:")
        for tool_name, issue in problematic_tools:
            logger.warning(f"  - {tool_name}: {issue}")
    logger.info(f"Using {len(valid_tools)} valid tools out of {len(coral_tools + agent_tools)} total tools")
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are an MCP-JFrog agent interacting with the tools from Coral Server and having your own JFrog tools. Your task is to perform any instructions coming from any agent related to JFrog Artifactory management.

            Follow these steps in order:
            1. Call wait_for_mentions from coral tools (timeoutMs: 30000) to receive mentions from other agents.
            2. When you receive a mention, keep the thread ID and the sender ID.
            3. Take 2 seconds to think about the content (instruction) of the message and check only from the list of your JFrog tools available for you to action.
            4. Check the tool schema and make a plan in steps for the JFrog task you want to perform.
            5. Only call the JFrog tools you need to perform for each step of the plan to complete the instruction in the content(Do not call any other tool/tools unnecessarily).
            6. Call get_artifacts_summary tool only at the end of the plan to get the summary of the artifacts.
            7. Take 3 seconds and think about the content and see if you have executed the instruction to the best of your ability and the tools. Make this your response as "answer".
            8. Use `send_message` from coral tools to send a message in the same thread ID to the sender Id you received the mention from, with content: "answer".
            9. If any error occurs, use `send_message` to send a message in the same thread ID to the sender Id you received the mention from, with content: "error".
            10. Always respond back to the sender agent even if you have no answer or error.
            11. Wait for 2 seconds and repeat the process from step 1.

            These are the list of coral tools: {coral_tools_description}
            These are the list of your JFrog tools: {agent_tools_description}"""
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
    agent = create_tool_calling_agent(model, valid_tools, prompt)
    return AgentExecutor(agent=agent, tools=valid_tools, verbose=True)

async def main():
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
    
    jfrog_tools = await client.get_tools(server_name="MCP-JFrog")
    logger.info(f"JFrog tools count: {len(jfrog_tools)}")
    
    
    agent_executor = await create_agent(coral_tools, jfrog_tools)

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