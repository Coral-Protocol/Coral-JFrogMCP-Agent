import asyncio
import os
import platform
import base64
import logging
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class BuildAndUploadArgs(BaseModel):
    project_path: str = Field(description="Path to the project directory containing pyproject.toml or setup.py")
    target_file_path: str = Field(description="Target directory path in JFrog repository (e.g., 'python-packages/' or 'python-packages'). The actual filename will be extracted from the built artifact.")
    repository: str = Field(description="JFrog repository name")
    build_required: bool = Field(description="Whether to build the project before uploading", default=True)

async def build_and_upload_to_jfrog(project_path: str, target_file_path: str, repository: str, build_required: bool = True) -> str:
    """
    Builds a Python project using uv (if required) and uploads the resulting artifacts to JFrog Artifactory.
    
    Args:
        project_path (str): Path to the project directory containing pyproject.toml or setup.py
        target_file_path (str): Target directory path in JFrog repository (e.g., 'python-packages/' or 'python-packages'). 
                               The actual filename will be extracted from the built artifact.
        repository (str): JFrog repository name
        build_required (bool): Whether to build the project before uploading (default: True)
    
    Returns:
        str: Success message or error message if either build or upload fails
    """
    try:
        # Step 1: Validate project path
        if not os.path.isdir(project_path):
            error = f"Directory does not exist: {project_path}"
            logger.error(error)
            return error
        
        # Check for pyproject.toml or setup.py
        if not (os.path.exists(os.path.join(project_path, "pyproject.toml")) or 
                os.path.exists(os.path.join(project_path, "setup.py"))):
            error = f"No pyproject.toml or setup.py found in {project_path}"
            logger.error(error)
            return error
        
        # Step 2: Build the project if required
        if build_required:
            proc = await asyncio.create_subprocess_exec(
                "uv", "build", project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                error = f"Build failed: {stderr.decode()}"
                logger.error(error)
                return error
                
        # Step 3: Locate build artifacts
        dist_path = os.path.join(project_path, "dist")
        if not os.path.exists(dist_path):
            error = f"No dist directory found at {dist_path}"
            logger.error(error)
            return error
            
        # Get all artifacts in dist directory
        artifacts = [os.path.join(dist_path, f) for f in os.listdir(dist_path) if os.path.isfile(os.path.join(dist_path, f))]
        if not artifacts:
            error = f"No build artifacts found in {dist_path}"
            logger.error(error)
            return error
            
        # Step 4: Get JFrog credentials
        email = os.getenv("JFROG_EMAIL")
        token = os.getenv("JFROG_TOKEN")
        jfrog_url = os.getenv("JFROG_URL")
        
        
        if not token:
            error = "JFROG_TOKEN environment variable is not set"
            logger.error(error)
            return error
            
        if not jfrog_url:
            error = "JFROG_URL environment variable is not set"
            logger.error(error)
            return error
            
        # Step 5: Upload artifacts
        system = platform.system().lower()
        success_messages = []
        error_messages = []
        
        for source_file_path in artifacts:
            # Extract filename from source path
            filename = os.path.basename(source_file_path)
            # Use target_file_path as directory, append filename
            if target_file_path.endswith('/'):
                upload_path = f"{target_file_path}{filename}"
            else:
                upload_path = f"{target_file_path}/{filename}"
            
            logger.info(f"Attempting to upload {source_file_path} to repository '{repository}' at path '{upload_path}'")
            
            if system in ["linux", "darwin"]:
                # Linux/WSL - use curl command
                curl_cmd = [
                    "curl", f"-u{email}:" + token,
                    "-T", source_file_path,
                    f"{jfrog_url}/artifactory/{repository}/{upload_path}"
                ]
                
                proc = await asyncio.create_subprocess_exec(
                    *curl_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    success_messages.append(f"Successfully uploaded {source_file_path} to {jfrog_url}/artifactory/{repository}/{upload_path}")
                else:
                    error_messages.append(f"Upload failed for {source_file_path}: {stderr.decode()}")
                    
            elif system == "windows":
                # Windows - use PowerShell
                auth_string = f"{email}:{token}"
                base64_auth = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
                
                powershell_cmd = [
                    "powershell", "-Command",
                    f'$base64AuthInfo = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("{auth_string}")); '
                    f'Invoke-WebRequest -Uri "{jfrog_url}/artifactory/{repository}/{upload_path}" -Headers @{{Authorization=("Basic {{0}}" -f $base64AuthInfo)}} -Method PUT -InFile "{source_file_path}"'
                ]
                
                logger.info(f"Executing PowerShell command: {' '.join(powershell_cmd)}")
                
                proc = await asyncio.create_subprocess_exec(
                    *powershell_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    success_messages.append(f"Successfully uploaded {source_file_path} to {jfrog_url}/artifactory/{repository}/{upload_path}")
                else:
                    stdout_output = stdout.decode() if stdout else ""
                    stderr_output = stderr.decode() if stderr else ""
                    error_messages.append(f"Upload failed for {source_file_path}: {stderr_output}\nStdout: {stdout_output}")
            else:
                error = f"Unsupported platform: {system}"
                logger.error(error)
                return error
                
        # Step 6: Compile results
        if error_messages:
            combined_errors = "\n".join(error_messages)
            logger.error(f"Some uploads failed:\n{combined_errors}")
            return combined_errors
            
        if success_messages:
            combined_success = "\n".join(success_messages)
            logger.info(f"All uploads successful:\n{combined_success}")
            return combined_success
            
        return "No artifacts were uploaded due to an unknown error"
        
    except Exception as e:
        error = f"Error occurred during build and upload: {str(e)}"
        logger.error(error)
        return error