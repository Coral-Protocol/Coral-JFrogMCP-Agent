import asyncio
import os
import logging
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class BuildProjectArgs(BaseModel):
    project_path: str = Field(description="Path to the project directory containing pyproject.toml or setup.py")
    build_required: bool = Field(description="Whether to build the project", default=True)

class UploadToJfrogArgs(BaseModel):
    project_path: str = Field(description="Path to the project directory containing built artifacts in dist/ folder")
    target_file_path: str = Field(description="Target directory path in JFrog repository (e.g., 'python-packages/' or 'python-packages'). The actual filename will be extracted from the built artifact.")
    repository: str = Field(description="JFrog repository name")

class JFrogScanArgs(BaseModel):
    project_directory: str = Field(description="Path to the project directory to scan for vulnerabilities and license compliance")

async def build_project(project_path: str, build_required: bool = True) -> str:
    """
    Builds a Python project using uv.
    
    Args:
        project_path (str): Path to the project directory containing pyproject.toml or setup.py
        build_required (bool): Whether to build the project (default: True)
    
    Returns:
        str: Success message with build artifacts location or error message if build fails
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
            logger.info(f"Building project at {project_path}")
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
            else:
                logger.info("Build completed successfully")
        else:
            logger.info("Build skipped as build_required=False")
                
        # Step 3: Locate and list build artifacts
        dist_path = os.path.join(project_path, "dist")
        if not os.path.exists(dist_path):
            error = f"No dist directory found at {dist_path}"
            logger.error(error)
            return error
            
        # Get all artifacts in dist directory
        artifacts = [f for f in os.listdir(dist_path) if os.path.isfile(os.path.join(dist_path, f))]
        if not artifacts:
            error = f"No build artifacts found in {dist_path}"
            logger.error(error)
            return error
        
        artifact_list = "\n".join([f"  - {artifact}" for artifact in artifacts])
        success_msg = f"Project built successfully. Build artifacts found in {dist_path}:\n{artifact_list}"
        logger.info(success_msg)
        return success_msg
        
    except Exception as e:
        error = f"Error occurred during build: {str(e)}"
        logger.error(error)
        return error

async def upload_to_jfrog(project_path: str, target_file_path: str, repository: str) -> str:
    """
    Uploads built artifacts from a project's dist directory to JFrog Artifactory using JFrog CLI.
    
    Args:
        project_path (str): Path to the project directory containing built artifacts in dist/ folder
        target_file_path (str): Target directory path in JFrog repository (e.g., 'python-packages/' or 'python-packages'). 
                               The actual filename will be extracted from the built artifact.
        repository (str): JFrog repository name
    
    Returns:
        str: Success message with the location of uploaded artifacts or error message if upload fails
    """
    try:
        # Step 1: Validate project path
        if not os.path.isdir(project_path):
            error = f"Directory does not exist: {project_path}"
            logger.error(error)
            return error
            
        # Step 2: Locate build artifacts
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
            
        # Step 3: JFrog CLI handles authentication automatically
        # Ensure JFrog CLI is configured and available
            
        # Step 4: Upload artifacts using JFrog CLI
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
            
            # Use JFrog CLI command: jf rt u <FILE_PATH> <REMOTE_REPOSITORY_PATH>
            jfrog_cmd = [
                "jf", "rt", "u", source_file_path, f"{repository}/{upload_path}"
            ]
            
            logger.info(f"Executing JFrog CLI command: {' '.join(jfrog_cmd)}")
            
            proc = await asyncio.create_subprocess_exec(
                *jfrog_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                success_messages.append(f"Successfully uploaded {source_file_path} to repository '{repository}' at path '{upload_path}'")
                logger.info(f"Upload successful: {stdout.decode().strip()}")
            else:
                error_msg = f"Upload failed for {source_file_path}: {stderr.decode()}"
                if stdout:
                    error_msg += f"\nStdout: {stdout.decode()}"
                error_messages.append(error_msg)
                logger.error(error_msg)
                
        # Step 5: Compile results
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
        error = f"Error occurred during upload: {str(e)}"
        logger.error(error)
        return error

async def jfrog_scan_project(project_directory: str) -> str:
    """
    Scans build artifacts in a project directory using JFrog CLI for vulnerabilities and license compliance.
    
    Args:
        project_directory (str): Path to the project directory containing build artifacts
        
    Returns:
        str: Scan results or error message if scan fails
    """
    try:
        # Step 1: Validate project directory
        if not os.path.isdir(project_directory):
            error = f"Directory does not exist: {project_directory}"
            logger.error(error)
            return error
        
        # Step 2: Check if JFrog CLI is available
        proc = await asyncio.create_subprocess_exec(
            "jf", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            error = "JFrog CLI (jf) is not installed or not available in PATH"
            logger.error(error)
            return error
        
        # Step 3: Check if JFrog is configured
        proc = await asyncio.create_subprocess_exec(
            "jf", "config", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            error = "JFrog CLI is not configured. Please run 'jf config' first"
            logger.error(error)
            return error
        
        # Step 4: Look for build artifacts in common build directories only
        build_artifacts = []
        common_build_dirs = ["dist", "build", "target", "out", "bin"]
        common_build_extensions = [".tar.gz", ".whl", ".egg", ".jar", ".war", ".ear", ".zip", ".rpm", ".deb", ".msi"]
        
        # Check common build directories for actual build artifacts
        for build_dir in common_build_dirs:
            build_path = os.path.join(project_directory, build_dir)
            if os.path.exists(build_path) and os.path.isdir(build_path):
                for file in os.listdir(build_path):
                    file_path = os.path.join(build_path, file)
                    if os.path.isfile(file_path):
                        # Only include files with recognized build artifact extensions
                        if any(file.endswith(ext) for ext in common_build_extensions):
                            build_artifacts.append(file_path)
                            logger.info(f"Found build artifact in {build_dir}/: {file}")
        
        # Step 5: Execute JFrog scan only on identified build artifacts
        if not build_artifacts:
            return f"No build artifacts found in common build directories ({', '.join(common_build_dirs)}) for {project_directory}. No scanning performed."
        
        # Scan each build artifact individually
        logger.info(f"Found {len(build_artifacts)} build artifacts to scan:")
        for artifact in build_artifacts:
            logger.info(f"  - {os.path.basename(artifact)}")
        
        scan_results = []
        for artifact_path in build_artifacts:
            artifact_name = os.path.basename(artifact_path)
            logger.info(f"Scanning build artifact: {artifact_name}")
            
            # Execute jf scan on the individual build file
            proc = await asyncio.create_subprocess_exec(
                "jf", "scan", artifact_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(artifact_path)
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                error_msg = f"Scan failed for {artifact_name}: {stderr.decode()}"
                logger.error(error_msg)
                scan_results.append(error_msg)
            else:
                scan_output = stdout.decode().strip()
                if scan_output:
                    scan_results.append(f"Scan results for {artifact_name}:\n{scan_output}")
                else:
                    scan_results.append(f"Scan completed for {artifact_name} (no issues found)")
        
        # Return combined scan results
        if scan_results:
            return f"JFrog scan completed for build artifacts:\n\n" + "\n\n".join(scan_results)
        else:
            return f"JFrog scan completed for {len(build_artifacts)} build artifacts (no issues found)"
        
    except Exception as e:
        error = f"Error occurred during JFrog scan: {str(e)}"
        logger.error(error)
        return error