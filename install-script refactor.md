# **Install Script: Refactoring the Frappe Easy Install Script**

The refactoring process transformed a single, long procedural script into a more structured, readable, and maintainable Python application. This document explores the key changes, comparing the "before" and "after" with code snippets to illustrate the benefits of each improvement.

### **1\. Improved Structure with Classes**

The most significant change was the introduction of classes to group related logic and manage state. This moves away from a long list of disconnected functions and toward a more object-oriented design.

#### **Before: Global Functions and Scattered Logic**

In the original script, configuration variables, paths, and actions were managed by numerous separate functions. This can make it difficult to track how data flows through the script.

*Original Snippet (Various Functions):*

def get\_frappe\_docker\_path():  
    return os.path.join(os.getcwd(), "frappe\_docker")

def start\_prod(project: str, ...):  
    \# ...  
    compose\_file\_name \= os.path.join(  
        os.path.expanduser("\~"),  
        f"{project}-compose.yml",  
    )  
    env\_file\_path \= os.path.join(  
        os.path.expanduser("\~"),  
        env\_file\_name,  
    )  
    \# ...

#### **After: The Config Class**

The Config class now acts as a single source of truth for all configuration settings. It's initialized once at the start and passed to the objects that need it. This makes the configuration explicit and easy to manage.

*Refactored Snippet:*

class Config:  
    """Manages configuration settings for the deployment."""  
    def \_\_init\_\_(self, args: argparse.Namespace):  
        self.project \= args.project  
        self.sites \= args.sites or \["site1.localhost"\]  
        \# ... other configurations ...

        \# All paths are calculated once and stored as attributes  
        self.frappe\_docker\_path \= os.path.join(os.getcwd(), FRAPPE\_DOCKER\_DIR)  
        self.env\_file\_path \= os.path.join(os.path.expanduser("\~"), f"{self.project}.env")  
        self.compose\_file\_path \= os.path.join(os.path.expanduser("\~"), f"{self.project}-compose.yml")  
        self.passwords\_file\_path \= os.path.join(os.path.expanduser("\~"), f"{self.project}-passwords.txt")

**Benefit:** Centralizes configuration, reduces redundancy, and makes the code cleaner. Any function needing a path or setting can get it from the config object.

### **2\. Robust Command Execution**

Executing shell commands is a critical but risky part of the script. The refactored version introduces a centralized, error-handled function for all subprocess calls.

#### **Before: Repeated try...except Blocks**

The original code had subprocess.run calls scattered throughout, each wrapped in its own try...except block. This led to a lot of repeated error-handling logic.

*Original Snippet:*

\# In start\_prod function  
try:  
    subprocess.run(command, cwd=frappe\_docker\_dir, stdout=f, check=True)  
except Exception:  
    logging.error("Docker Compose generation failed", exc\_info=True)  
    cprint("\\nGenerating Compose File failed\\n")  
    sys.exit(1)

\# In another function, create\_site  
try:  
    subprocess.run(command, check=True)  
except Exception as e:  
    logging.error(f"Bench site creation failed for {sitename}", exc\_info=True)  
    cprint(f"Bench Site creation failed for {sitename}\\n", e)

#### **After: A Central run\_command Wrapper**

A single run\_command function now handles all subprocess calls. It includes comprehensive error handling for CalledProcessError (command fails) and FileNotFoundError (command doesn't exist), providing clearer feedback to the user and cleaner logs.

*Refactored Snippet:*

def run\_command(command: List\[str\], cwd: Optional\[str\] \= None, check: bool \= True, stdout=None) \-\> subprocess.CompletedProcess:  
    """Executes a subprocess command and handles potential errors."""  
    try:  
        logging.info(f"Running command: {' '.join(command)}")  
        return subprocess.run(command, cwd=cwd, check=check, stdout=stdout, stderr=subprocess.PIPE, text=True)  
    except subprocess.CalledProcessError as e:  
        logging.error(f"Command failed: {' '.join(command)}\\nError: {e.stderr}", exc\_info=True)  
        cprint(f"An error occurred while executing a command. Check '{LOG\_FILE}' for details.", "error")  
        cprint(f"Error details: {e.stderr}", "error")  
        sys.exit(1)  
    except FileNotFoundError:  
        \# ... handles missing command error ...  
        sys.exit(1)

**Benefit:** DRY (Don't Repeat Yourself) principle applied. Error handling is consistent, more detailed, and easier to improve in one place.

### **3\. Separation of Concerns**

The refactored script separates different areas of logic into dedicated classes, making the code's purpose much clearer.

#### **Before: Intermingled Logic**

In the original script, the start\_prod function was responsible for almost everything: checking the repo, managing paths, writing .env files, generating the compose file, and starting containers. This makes the function very long and hard to debug.

#### **After: EnvironmentManager and DockerComposeManager**

This logic is now split into two focused classes:

1. EnvironmentManager: Handles all file system interactions related to the .env file (reading and writing).  
2. DockerComposeManager: Manages all docker compose commands (generating the config, starting services, executing commands in containers).

*Refactored Snippet (DockerComposeManager):*

class DockerComposeManager:  
    """Manages Docker Compose operations."""  
    def \_\_init\_\_(self, config: Config):  
        self.config \= config

    def generate\_compose\_file(self):  
        """Generates the final docker-compose.yml file."""  
        \# ... logic for building the 'docker compose config' command ...  
        with open(self.config.compose\_file\_path, "w") as f:  
            run\_command(command, cwd=self.config.frappe\_docker\_path, stdout=f)

    def start\_services(self):  
        """Starts the Docker containers."""  
        \# ... logic for building the 'docker compose up' command ...  
        run\_command(command)

**Benefit:** Each class has a single responsibility, making the code easier to understand, test, and extend. The main deploy\_production function becomes a high-level coordinator, which is much more readable.

### **4\. Improved Readability and Constants**

Minor changes significantly improve the code's readability and maintainability.

#### **Before: Magic Strings**

The original code used hardcoded strings like "frappe\_docker", "frappe\_docker-main", and URLs directly in the logic.

*Original Snippet:*

def clone\_frappe\_docker\_repo() \-\> None:  
    try:  
        urllib.request.urlretrieve(  
            "\[https://github.com/frappe/frappe\_docker/archive/refs/heads/main.zip\](https://github.com/frappe/frappe\_docker/archive/refs/heads/main.zip)",  
            "frappe\_docker.zip",  
        )  
        \# ...  
        move("frappe\_docker-main", "frappe\_docker")

#### **After: Centralized Constants**

These strings are moved to the top of the file as constants. If a URL or directory name ever changes, it only needs to be updated in one place.

*Refactored Snippet:*

\# \--- Constants \---  
FRAPPE\_DOCKER\_URL \= "\[https://github.com/frappe/frappe\_docker/archive/refs/heads/main.zip\](https://github.com/frappe/frappe\_docker/archive/refs/heads/main.zip)"  
FRAPPE\_DOCKER\_ZIP \= "frappe\_docker.zip"  
FRAPPE\_DOCKER\_EXTRACTED \= "frappe\_docker-main"  
FRAPPE\_DOCKER\_DIR \= "frappe\_docker"  
LOG\_FILE \= "easy-install.log"

\# ... in the function ...  
def clone\_frappe\_docker\_repo():  
    \# ...  
    urllib.request.urlretrieve(FRAPPE\_DOCKER\_URL, FRAPPE\_DOCKER\_ZIP)  
    \# ...  
    move(FRAPPE\_DOCKER\_EXTRACTED, FRAPPE\_DOCKER\_DIR)  
