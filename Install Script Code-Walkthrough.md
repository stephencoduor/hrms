# **Code Walkthrough: A Deep Dive into the Refactored Script**

## Table of Contents

* [Overview](#code-walkthrough-a-deep-dive-into-the-refactored-script)
* [1. Initial Setup and Configuration](#1-initial-setup-and-configuration)

  * [Constants and Logging](#constants-and-logging)
* [2. Utility Classes and Helper Functions](#2-utility-classes-and-helper-functions)

  * [Color and cprint](#color-and-cprint)
  * [Config Class](#config-class)
  * [run\_command](#run_command)
* [3. Core Logic: Preparing the Environment](#3-core-logic-preparing-the-environment)
* [4. Managing Configuration and Docker](#4-managing-configuration-and-docker)

  * [EnvironmentManager Class](#environmentmanager-class)
  * [DockerComposeManager Class](#dockercomposemanager-class)
* [5. High-Level Workflows: deploy and upgrade](#5-high-level-workflows-deploy-and-upgrade)
* [6. Command-Line Interface and Main Entry Point](#6-command-line-interface-and-main-entry-point)

---

This document provides a detailed, step-by-step explanation of the `easy_install_refactored.py` script. We will explore each section to understand its purpose, how it works, and how it contributes to the overall goal of automating Frappe Docker deployments.

---

### **1. Initial Setup and Configuration**

The script begins by setting up its foundational components: global constants, logging, and data structures for managing configuration and output.

#### **Constants and Logging**

This section defines static variables that are used throughout the script. Using constants instead of "magic strings" (hardcoded text) is a core principle of clean code.

```python
# --- Constants ---
FRAPPE_DOCKER_URL = "https://github.com/frappe/frappe_docker/archive/refs/heads/main.zip"
FRAPPE_DOCKER_ZIP = "frappe_docker.zip"
FRAPPE_DOCKER_EXTRACTED = "frappe_docker-main"
FRAPPE_DOCKER_DIR = "frappe_docker"
LOG_FILE = "easy-install.log"

# --- Basic Setup ---
logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",  # 'w' overwrites log file on each run
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
```

*What it does:* It sets up file paths, URLs, and configures a log file (`easy-install.log`).

---

### **2. Utility Classes and Helper Functions**

These are the reusable building blocks of the script.

#### **Color and cprint**

```python
class Color:
    """Holds ANSI color codes for console output."""
    RED = "\033[31m"
    GREEN = "\33[92m"
    YELLOW = "\33[93m"
    RESET = "\033[0m"

def cprint(message: str, level: str = "error"):
    """Prints colorful messages to the console."""
    color_map = {
        "error": Color.RED,
        "success": Color.GREEN,
        "warning": Color.YELLOW,
    }
    color = color_map.get(level.lower(), Color.RED)
    print(f"{color}{message}{Color.RESET}")
```

#### **Config Class**

```python
class Config:
    """Manages configuration settings for the deployment."""
    def __init__(self, args: argparse.Namespace):
        self.project = args.project
        self.sites = args.sites or ["site1.localhost"]
        self.email = args.email
        self.apps = args.apps
        self.is_https = not args.no_ssl
        self.http_port = args.http_port
        self.force_pull = args.force_pull

        # Paths calculated once and stored
        self.frappe_docker_path = os.path.join(os.getcwd(), FRAPPE_DOCKER_DIR)
        self.env_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}.env")
        self.compose_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}-compose.yml")
```

#### **run\_command**

```python
def run_command(command: List[str], cwd: Optional[str] = None, check: bool = True, stdout=None) -> subprocess.CompletedProcess:
    """Executes a subprocess command and handles potential errors."""
    try:
        logging.info(f"Running command: {' '.join(command)}")
        return subprocess.run(command, cwd=cwd, check=check, stdout=stdout, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(command)}\nError: {e.stderr}", exc_info=True)
        cprint("An error occurred while executing a command. See log for details.", "error")
        cprint(f"Error details: {e.stderr.strip()}", "error")
        sys.exit(1)
    except FileNotFoundError:
        cprint(f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?", "error")
        sys.exit(1)
```

---

### **3. Core Logic: Preparing the Environment**

```python
def setup_environment(force_pull: bool):
    """Ensures Docker is installed and the frappe_docker repository is available."""
    install_container_runtime()
    if force_pull and os.path.exists(FRAPPE_DOCKER_DIR):
        cprint("\n--force-pull specified, removing existing frappe_docker directory.", "warning")
        shutil.rmtree(FRAPPE_DOCKER_DIR, ignore_errors=True)

    if not os.path.exists(FRAPPE_DOCKER_DIR):
        clone_frappe_docker_repo()

def clone_frappe_docker_repo():
    """Downloads and extracts the frappe_docker repository from GitHub."""
    cprint("Downloading frappe_docker repository...", "success")
    try:
        urllib.request.urlretrieve(FRAPPE_DOCKER_URL, FRAPPE_DOCKER_ZIP)
        unpack_archive(FRAPPE_DOCKER_ZIP, ".")
        move(FRAPPE_DOCKER_EXTRACTED, FRAPPE_DOCKER_DIR)
        os.remove(FRAPPE_DOCKER_ZIP)
        logging.info("frappe_docker repository is ready.")
    except Exception as e:
        cprint(f"Failed to download or extract repository: {e}", "error")
        sys.exit(1)
```

---

### **4. Managing Configuration and Docker**

#### **EnvironmentManager Class**

```python
class EnvironmentManager:
    @staticmethod
    def read_env(file_path: str) -> Dict[str, str]:
        """Reads a .env file, ignoring comments and empty lines."""
        env_vars = {}
        with open(file_path) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                key, value = line.strip().split("=", 1)
                env_vars[key] = value
        return env_vars

    @staticmethod
    def write_env(config: Config, db_pass: str, admin_pass: str):
        """Constructs and writes the .env file from the config object."""
        quoted_sites = ",".join([f"`{site}`" for site in config.sites]).strip(",")
        env_content = {
            "ERPNEXT_VERSION": "v15.25.1",
            "DB_PASSWORD": db_pass,
            "SITES": quoted_sites,
            "LETSENCRYPT_EMAIL": config.email or "user@example.com",
            "SITE_ADMIN_PASS": admin_pass,
        }
        with open(config.env_file_path, "w") as f:
            for key, value in env_content.items():
                f.write(f"{key}={value}\n")
```

#### **DockerComposeManager Class**

```python
class DockerComposeManager:
    def __init__(self, config: Config):
        self.config = config

    def generate_compose_file(self):
        """Merges override files to generate the final docker-compose.yml."""
        cprint("Generating Docker Compose file...", "success")
        command = [
            "docker", "compose", "--project-name", self.config.project,
            "-f", "compose.yaml",
            "-f", "overrides/compose.mariadb.yaml",
            "-f", "overrides/compose.redis.yaml",
            "-f", "overrides/compose.https.yaml" if self.config.is_https else "overrides/compose.noproxy.yaml",
            "-f", "overrides/compose.backup-cron.yaml",
            "--env-file", self.config.env_file_path,
            "config",
        ]
        with open(self.config.compose_file_path, "w") as f:
            run_command(command, cwd=self.config.frappe_docker_path, stdout=f)

    def start_services(self):
        """Starts the Docker containers in detached mode."""
        cprint("Starting Docker services...", "success")
        command = [
            "docker", "compose", "-p", self.config.project,
            "-f", self.config.compose_file_path, "up", "--remove-orphans", "-d"
        ]
        run_command(command)
```

---

### **5. High-Level Workflows: deploy and upgrade**

```python
def deploy_production(config: Config):
    """Handles the entire production deployment process."""
    cprint(f"Starting new deployment for project: {config.project}", "success")
    setup_environment(config.force_pull)

    if os.path.exists(config.env_file_path):
        cprint("Existing .env file found. Reusing passwords.", "warning")
        env = EnvironmentManager.read_env(config.env_file_path)
        db_pass, admin_pass = env["DB_PASSWORD"], env["SITE_ADMIN_PASS"]
    else:
        cprint("Generating new passwords.", "success")
        db_pass, admin_pass = generate_pass(9), generate_pass()

    EnvironmentManager.write_env(config, db_pass, admin_pass)

    compose_manager = DockerComposeManager(config)
    compose_manager.generate_compose_file()
    compose_manager.start_services()

    for site in config.sites:
        cprint(f"Creating site: {site}", "success")
        site_command = [
            "bench", "new-site", site, "--no-mariadb-socket",
            f"--db-root-password={db_pass}", f"--admin-password={admin_pass}",
        ]
        for app in config.apps:
            site_command.extend(["--install-app", app])
        compose_manager.exec_in_backend(site_command)

    cprint("\nDeployment successful!", "success")
```

---

### **6. Command-Line Interface and Main Entry Point**

```python
def create_parser() -> argparse.ArgumentParser:
    """Creates and configures the argument parser."""
    parser = argparse.ArgumentParser(description="Easy install script for Frappe Framework")
    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Available commands")

    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy a new production instance")
    # ... add arguments like --project, --sitename
    deploy_parser.set_defaults(func=deploy_production)

    return parser

def main():
    """Main entry point of the script."""
    parser = create_parser()
    args = parser.parse_args()

    config = Config(args)
    args.func(config)

if __name__ == "__main__":
    main()
```
