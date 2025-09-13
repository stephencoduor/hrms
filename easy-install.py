#!/usr/bin/env python3

import argparse
import base64
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from shutil import move, unpack_archive, which
from typing import Dict, List, Optional

# --- Constants ---
FRAPPE_DOCKER_URL = "https://github.com/frappe/frappe_docker/archive/refs/heads/main.zip"
FRAPPE_DOCKER_ZIP = "frappe_docker.zip"
FRAPPE_DOCKER_EXTRACTED = "frappe_docker-main"
FRAPPE_DOCKER_DIR = "frappe_docker"
LOG_FILE = "easy-install.log"

# --- Basic Setup ---
logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# --- Utility Classes ---

class Color:
    """Holds ANSI color codes for console output."""
    RED = "\033[31m"
    GREEN = "\33[92m"
    YELLOW = "\33[93m"
    RESET = "\033[0m"

class Config:
    """Manages configuration settings for the deployment."""

    def __init__(self, args: argparse.Namespace):
        self.project = args.project
        self.sites = args.sites or ["site1.localhost"]
        self.email = args.email
        self.apps = args.apps
        self.cronstring = args.backup_schedule
        self.erpnext_version = args.version
        self.image = args.image
        self.tag = args.version
        self.is_https = not args.no_ssl
        self.http_port = args.http_port
        self.force_pull = args.force_pull

        self.frappe_docker_path = os.path.join(os.getcwd(), FRAPPE_DOCKER_DIR)
        self.env_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}.env")
        self.compose_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}-compose.yml")
        self.passwords_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}-passwords.txt")

# --- Helper Functions ---

def cprint(message: str, level: str = "error"):
    """Prints colorful messages to the console."""
    color_map = {
        "error": Color.RED,
        "success": Color.GREEN,
        "warning": Color.YELLOW,
    }
    color = color_map.get(level.lower(), Color.RED)
    print(f"{color}{message}{Color.RESET}")

def run_command(command: List[str], cwd: Optional[str] = None, check: bool = True, stdout=None) -> subprocess.CompletedProcess:
    """Executes a subprocess command and handles potential errors."""
    try:
        logging.info(f"Running command: {' '.join(command)}")
        return subprocess.run(command, cwd=cwd, check=check, stdout=stdout, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(command)}\nError: {e.stderr}", exc_info=True)
        cprint(f"An error occurred while executing a command. Check '{LOG_FILE}' for details.", "error")
        cprint(f"Error details: {e.stderr}", "error")
        sys.exit(1)
    except FileNotFoundError:
        logging.error(f"Command not found: {command[0]}", exc_info=True)
        cprint(f"Error: Command '{command[0]}' not found. Please ensure it is installed and in your PATH.", "error")
        sys.exit(1)

def generate_pass(length: int = 12) -> str:
    """Generate random hash using best available randomness source."""
    import math
    import secrets
    return secrets.token_hex(math.ceil(length / 2))[:length]

# --- Core Logic ---

def setup_environment(force_pull: bool):
    """Ensures Docker is installed and the frappe_docker repository is available."""
    install_container_runtime()
    if force_pull and os.path.exists(FRAPPE_DOCKER_DIR):
        cprint("\nForce pulling frappe_docker again...", "warning")
        shutil.rmtree(FRAPPE_DOCKER_DIR, ignore_errors=True)

    if not os.path.exists(FRAPPE_DOCKER_DIR):
        clone_frappe_docker_repo()

def clone_frappe_docker_repo():
    """Downloads and extracts the frappe_docker repository."""
    cprint("Downloading frappe_docker repository...", "warning")
    try:
        urllib.request.urlretrieve(FRAPPE_DOCKER_URL, FRAPPE_DOCKER_ZIP)
        logging.info("Downloaded frappe_docker zip file from GitHub")
        unpack_archive(FRAPPE_DOCKER_ZIP, ".")
        move(FRAPPE_DOCKER_EXTRACTED, FRAPPE_DOCKER_DIR)
        logging.info("Unzipped and Renamed frappe_docker")
        os.remove(FRAPPE_DOCKER_ZIP)
        logging.info("Removed the downloaded zip file")
        cprint("Successfully downloaded frappe_docker.", "success")
    except Exception as e:
        logging.error("Download and unzip failed", exc_info=True)
        cprint(f"Cloning frappe_docker Failed: {e}", "error")
        sys.exit(1)

def install_container_runtime(runtime="docker"):
    """Checks for and installs Docker if it's not present."""
    if which(runtime):
        cprint(f"{runtime.title()} is already installed.", "success")
        return

    cprint("Docker is not installed, attempting installation...", "warning")
    if platform.system() != "Linux":
        cprint(f"This script cannot automatically install Docker on {platform.system()}.", "error")
        cprint("Please install Docker manually and run this script again.", "error")
        sys.exit(1)

    try:
        # Using the official get-docker.sh script
        get_docker_script = run_command(["curl", "-fsSL", "https://get.docker.com"], stdout=subprocess.PIPE)
        run_command(["sudo", "/bin/bash"], input=get_docker_script.stdout)
        run_command(["sudo", "usermod", "-aG", "docker", str(os.getenv("USER"))])
        cprint("Docker installed. You may need to log out and log back in for group changes to take effect.", "success")
        cprint("Restarting Docker service...", "warning")
        run_command(["sudo", "systemctl", "restart", "docker.service"])
        time.sleep(5)
    except Exception as e:
        logging.error("Installing Docker failed", exc_info=True)
        cprint(f"Failed to install Docker: {e}", "error")
        cprint("Try installing Docker manually and re-run this script.", "error")
        sys.exit(1)

class EnvironmentManager:
    """Handles reading from and writing to .env files."""

    @staticmethod
    def read_env(file_path: str) -> Dict[str, str]:
        """Reads key-value pairs from an environment file."""
        env_vars = {}
        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key] = value
        except FileNotFoundError:
            logging.warning(f"Environment file not found at {file_path}")
        return env_vars

    @staticmethod
    def write_env(config: Config, db_pass: str, admin_pass: str):
        """Writes configuration to the .env file."""
        quoted_sites = ",".join([f"`{site}`" for site in config.sites])
        default_env = EnvironmentManager.read_env(os.path.join(config.frappe_docker_path, "example.env"))
        erpnext_version = config.erpnext_version or default_env.get("ERPNEXT_VERSION", "latest")

        env_content = {
            "ERPNEXT_VERSION": erpnext_version,
            "DB_PASSWORD": db_pass,
            "SITES": quoted_sites,
            "LETSENCRYPT_EMAIL": config.email or "",
            "SITE_ADMIN_PASS": admin_pass,
            "BACKUP_CRONSTRING": f'"{config.cronstring}"',
            "DB_HOST": "db",
            "DB_PORT": "3306",
            "REDIS_CACHE": "redis-cache:6379",
            "REDIS_QUEUE": "redis-queue:6379",
            "REDIS_SOCKETIO": "redis-socketio:6379",
            "PULL_POLICY": "missing",
        }

        if not config.is_https and config.http_port:
            env_content["HTTP_PUBLISH_PORT"] = config.http_port
        if config.image:
            env_content["CUSTOM_IMAGE"] = config.image
        if config.tag:
            env_content["CUSTOM_TAG"] = config.tag

        with open(config.env_file_path, "w") as f:
            for key, value in env_content.items():
                f.write(f"{key}={value}\n")
        cprint(f"Configuration written to {config.env_file_path}", "success")


class DockerComposeManager:
    """Manages Docker Compose operations."""

    def __init__(self, config: Config):
        self.config = config

    def generate_compose_file(self):
        """Generates the final docker-compose.yml file."""
        cprint("Generating Docker Compose file...", "warning")
        compose_files = [
            "compose.yaml",
            "overrides/compose.mariadb.yaml",
            "overrides/compose.redis.yaml",
            "overrides/compose.https.yaml" if self.config.is_https else "overrides/compose.noproxy.yaml",
            "overrides/compose.backup-cron.yaml",
        ]

        command = [
            "docker", "compose",
            "--project-name", self.config.project,
            "--env-file", self.config.env_file_path,
        ]

        for f in compose_files:
            command.extend(["-f", f])

        command.append("config")

        with open(self.config.compose_file_path, "w") as f:
            run_command(command, cwd=self.config.frappe_docker_path, stdout=f)
        cprint(f"Docker Compose file generated at {self.config.compose_file_path}", "success")


    def start_services(self):
        """Starts the Docker containers."""
        cprint("Starting services with Docker Compose...", "warning")
        command = [
            "docker", "compose",
            "-p", self.config.project,
            "-f", self.config.compose_file_path,
            "up", "-d",
            "--remove-orphans",
            "--force-recreate"
        ]
        run_command(command)
        cprint("All services are up and running.", "success")

    def exec_in_backend(self, command: List[str], interactive: bool = False):
        """Executes a command inside the backend container."""
        cprint(f"Executing in backend: {' '.join(command)}", "warning")
        base_cmd = ["docker", "compose", "-p", self.config.project, "exec"]
        if interactive:
            base_cmd.append("-it")
        base_cmd.append("backend")
        
        run_command(base_cmd + command)


def deploy_production(config: Config):
    """Handles the entire production deployment process."""
    setup_environment(config.force_pull)

    # Manage passwords and .env file
    if os.path.exists(config.env_file_path):
        cprint(f"Existing environment file found at {config.env_file_path}. Reusing passwords.", "warning")
        env_vars = EnvironmentManager.read_env(config.env_file_path)
        db_pass = env_vars.get("DB_PASSWORD", generate_pass(9))
        admin_pass = env_vars.get("SITE_ADMIN_PASS", generate_pass())
        config.sites = env_vars.get("SITES", "").replace("`", "").split(",") or config.sites
    else:
        cprint("Generating new passwords.", "warning")
        db_pass = generate_pass(9)
        admin_pass = generate_pass()
        with open(config.passwords_file_path, "w") as f:
            f.write(f"ADMINISTRATOR_PASSWORD={admin_pass}\n")
            f.write(f"MARIADB_ROOT_PASSWORD={db_pass}\n")
        cprint(f"Passwords saved to {config.passwords_file_path}", "success")
    
    EnvironmentManager.write_env(config, db_pass, admin_pass)
    
    # Manage Docker Compose
    compose_manager = DockerComposeManager(config)
    compose_manager.generate_compose_file()
    compose_manager.start_services()

    # Create sites
    for site in config.sites:
        cprint(f"Creating site: {site}", "warning")
        site_cmd = [
            "bench", "new-site", site,
            "--no-mariadb-socket",
            f"--db-root-password={db_pass}",
            f"--admin-password={admin_pass}"
        ]
        for app in config.apps:
            site_cmd.extend(["--install-app", app])
        compose_manager.exec_in_backend(site_cmd)
    
    cprint("Deployment successful!", "success")
    cprint(f"MariaDB root password: {db_pass}", "success")
    cprint(f"Administrator password: {admin_pass}", "success")

def upgrade_production(config: Config):
    """Handles upgrading an existing production deployment."""
    setup_environment(config.force_pull)

    if not os.path.exists(config.env_file_path):
        cprint(f"Environment file not found for project '{config.project}'. Cannot upgrade.", "error")
        sys.exit(1)

    env_vars = EnvironmentManager.read_env(config.env_file_path)
    db_pass = env_vars["DB_PASSWORD"]
    admin_pass = env_vars["SITE_ADMIN_PASS"]

    EnvironmentManager.write_env(config, db_pass, admin_pass)
    
    compose_manager = DockerComposeManager(config)
    compose_manager.generate_compose_file()
    compose_manager.start_services()

    cprint("Migrating sites...", "warning")
    compose_manager.exec_in_backend(["bench", "--site", "all", "migrate"])
    cprint("Upgrade successful!", "success")

# --- Argument Parsing ---

def create_parser() -> argparse.ArgumentParser:
    """Creates and configures the argument parser."""
    parser = argparse.ArgumentParser(description="Easy install script for Frappe Framework")
    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Available commands")

    # Parent parser for common options
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("-n", "--project", default="frappe", help="Project Name")
    parent_parser.add_argument("-g", "--backup-schedule", default="@every 6h", help="Backup schedule cronstring")
    parent_parser.add_argument("-i", "--image", help="Custom Docker image to use")
    parent_parser.add_argument("-v", "--version", help="Version tag for the image")
    parent_parser.add_argument("-q", "--no-ssl", action="store_true", help="Disable HTTPS setup")
    parent_parser.add_argument("-m", "--http-port", default="8080", help="HTTP port to publish (if no-ssl)")
    parent_parser.add_argument("-l", "--force-pull", action="store_true", help="Force re-download of frappe_docker")

    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy a new production instance", parents=[parent_parser])
    deploy_parser.add_argument("-s", "--sitename", dest="sites", action="append", default=[], help="Site name to create")
    deploy_parser.add_argument("-e", "--email", help="Email for Let's Encrypt SSL")
    deploy_parser.add_argument("-a", "--app", dest="apps", action="append", default=[], help="App to install on site")
    deploy_parser.set_defaults(func=deploy_production)

    # Upgrade command
    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade an existing instance", parents=[parent_parser])
    upgrade_parser.set_defaults(func=upgrade_production)
    
    # Exec command
    exec_parser = subparsers.add_parser("exec", help="Execute a command in the backend container")
    exec_parser.add_argument("project", help="The project name to execute in")
    exec_parser.add_argument("command", nargs=argparse.REMAINDER, help="The command to execute")
    
    return parser

def main():
    """Main entry point of the script."""
    parser = create_parser()
    args = parser.parse_args()
    
    if args.subcommand == "exec":
        config = argparse.Namespace(project=args.project)
        compose_manager = DockerComposeManager(config)
        compose_manager.exec_in_backend(args.command, interactive=True if not args.command else False)
    else:
        config = Config(args)
        if config.email and "example.com" in config.email:
            cprint("Email addresses from 'example.com' are not allowed for SSL.", "error")
            sys.exit(1)
        args.func(config)


if __name__ == "__main__":
    main()
