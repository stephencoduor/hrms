# **Install Script: Refactoring the Frappe Easy Install Script**

The refactoring process transformed a single, long procedural script into a more structured, readable, and maintainable Python application. This document explores the key changes, comparing the "before" and "after" with code snippets to illustrate the benefits of each improvement.

---

### **1. Improved Structure with Classes**

The most significant change was the introduction of classes to group related logic and manage state. This moves away from a long list of disconnected functions and toward a more object-oriented design.

#### **Before: Global Functions and Scattered Logic**

In the original script, configuration variables, paths, and actions were managed by numerous separate functions. This can make it difficult to track how data flows through the script.

```python
# Original Snippet (Various Functions)
def get_frappe_docker_path():
    return os.path.join(os.getcwd(), "frappe_docker")

def start_prod(project: str, ...):
    # ...
    compose_file_name = os.path.join(
        os.path.expanduser("~"),
        f"{project}-compose.yml",
    )
    env_file_path = os.path.join(
        os.path.expanduser("~"),
        env_file_name,
    )
    # ...
```

#### **After: The Config Class**

The Config class now acts as a single source of truth for all configuration settings. It's initialized once at the start and passed to the objects that need it. This makes the configuration explicit and easy to manage.

```python
# Refactored Snippet
class Config:
    """Manages configuration settings for the deployment."""
    def __init__(self, args: argparse.Namespace):
        self.project = args.project
        self.sites = args.sites or ["site1.localhost"]
        # ... other configurations ...

        # All paths are calculated once and stored as attributes
        self.frappe_docker_path = os.path.join(os.getcwd(), FRAPPE_DOCKER_DIR)
        self.env_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}.env")
        self.compose_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}-compose.yml")
        self.passwords_file_path = os.path.join(os.path.expanduser("~"), f"{self.project}-passwords.txt")
```

**Benefit:** Centralizes configuration, reduces redundancy, and makes the code cleaner. Any function needing a path or setting can get it from the config object.

---

### **2. Robust Command Execution**

Executing shell commands is a critical but risky part of the script. The refactored version introduces a centralized, error-handled function for all subprocess calls.

#### **Before: Repeated try...except Blocks**

The original code had `subprocess.run` calls scattered throughout, each wrapped in its own try...except block. This led to a lot of repeated error-handling logic.

```python
# Original Snippet
# In start_prod function
try:
    subprocess.run(command, cwd=frappe_docker_dir, stdout=f, check=True)
except Exception:
    logging.error("Docker Compose generation failed", exc_info=True)
    cprint("\nGenerating Compose File failed\n")
    sys.exit(1)

# In another function, create_site
try:
    subprocess.run(command, check=True)
except Exception as e:
    logging.error(f"Bench site creation failed for {sitename}", exc_info=True)
    cprint(f"Bench Site creation failed for {sitename}\n", e)
```

#### **After: A Central run\_command Wrapper**

A single `run_command` function now handles all subprocess calls. It includes comprehensive error handling for `CalledProcessError` (command fails) and `FileNotFoundError` (command doesn't exist), providing clearer feedback to the user and cleaner logs.

```python
# Refactored Snippet
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
        # ... handles missing command error ...
        sys.exit(1)
```

**Benefit:** DRY (Don't Repeat Yourself) principle applied. Error handling is consistent, more detailed, and easier to improve in one place.

---

### **3. Separation of Concerns**

The refactored script separates different areas of logic into dedicated classes, making the code's purpose much clearer.

#### **Before: Intermingled Logic**

In the original script, the `start_prod` function was responsible for almost everything: checking the repo, managing paths, writing `.env` files, generating the compose file, and starting containers. This makes the function very long and hard to debug.

#### **After: EnvironmentManager and DockerComposeManager**

This logic is now split into two focused classes:

1. **EnvironmentManager**: Handles all file system interactions related to the `.env` file (reading and writing).
2. **DockerComposeManager**: Manages all docker compose commands (generating the config, starting services, executing commands in containers).

```python
# Refactored Snippet (DockerComposeManager)
class DockerComposeManager:
    """Manages Docker Compose operations."""
    def __init__(self, config: Config):
        self.config = config

    def generate_compose_file(self):
        """Generates the final docker-compose.yml file."""
        # ... logic for building the 'docker compose config' command ...
        with open(self.config.compose_file_path, "w") as f:
            run_command(command, cwd=self.config.frappe_docker_path, stdout=f)

    def start_services(self):
        """Starts the Docker containers."""
        # ... logic for building the 'docker compose up' command ...
        run_command(command)
```

**Benefit:** Each class has a single responsibility, making the code easier to understand, test, and extend. The main `deploy_production` function becomes a high-level coordinator, which is much more readable.

---

### **4. Improved Readability and Constants**

Minor changes significantly improve the code's readability and maintainability.

#### **Before: Magic Strings**

The original code used hardcoded strings like `"frappe_docker"`, `"frappe_docker-main"`, and URLs directly in the logic.

```python
# Original Snippet
def clone_frappe_docker_repo() -> None:
    try:
        urllib.request.urlretrieve(
            "https://github.com/frappe/frappe_docker/archive/refs/heads/main.zip",
            "frappe_docker.zip",
        )
        # ...
        move("frappe_docker-main", "frappe_docker")
```

#### **After: Centralized Constants**

These strings are moved to the top of the file as constants. If a URL or directory name ever changes, it only needs to be updated in one place.

```python
# Refactored Snippet
# --- Constants ---
FRAPPE_DOCKER_URL = "https://github.com/frappe/frappe_docker/archive/refs/heads/main.zip"
FRAPPE_DOCKER_ZIP = "frappe_docker.zip"
FRAPPE_DOCKER_EXTRACTED = "frappe_docker-main"
FRAPPE_DOCKER_DIR = "frappe_docker"
LOG_FILE = "easy-install.log"

# ... in the function ...
def clone_frappe_docker_repo():
    # ...
    urllib.request.urlretrieve(FRAPPE_DOCKER_URL, FRAPPE_DOCKER_ZIP)
    # ...
    move(FRAPPE_DOCKER_EXTRACTED, FRAPPE_DOCKER_DIR)
```

**Benefit:** Constants make the script easier to maintain and reduce the chance of introducing bugs due to inconsistent string usage.
