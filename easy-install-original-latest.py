#!/usr/bin/env python3

import argparse
import base64
import json
import logging
import os
import platform
import secrets
import shutil
import string
import subprocess
import sys
import time
import urllib.request
from shutil import move, unpack_archive, which

# --- Setup Logging ---
logging.basicConfig(
    filename="easy-install.log",
    filemode="w",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

def cprint(*args, level: int = 1):
    """
    Logs colorful messages to the console.
    level=1: RED (Error), level=2: GREEN (Success), level=3: YELLOW (Warning/Info)
    """
    CRED = "\033[31m"
    CGRN = "\33[92m"
    CYLW = "\33[93m"
    CEND = "\033[0m"
    message = " ".join(map(str, args))
    color_map = {1: CRED, 2: CGRN, 3: CYLW}
    print(f"{color_map.get(level, '')}{message}{CEND}")
    logging.info(message)

def run_command(command, cwd=None, env=None, check=True, capture_output=False):
    """A helper function to run a command, log it, and handle errors."""
    cprint(f"> {' '.join(command)}", level=3)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout_lines = []
        # Stream stdout
        for line in process.stdout:
            print(line, end='')
            stdout_lines.append(line)

        # Wait for the process to finish and get stderr
        _, stderr = process.communicate()

        if stderr:
            cprint(f"--- STDERR ---\n{stderr}", level=1)

        if process.returncode != 0 and check:
            cprint(f"An error occurred while executing command: {' '.join(command)}", level=1)
            sys.exit(1)

        if capture_output:
            return "".join(stdout_lines).strip()

    except FileNotFoundError:
        cprint(f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?", level=1)
        sys.exit(1)
    except Exception as e:
        cprint(f"An unexpected error occurred: {e}", level=1)
        logging.error("Command execution failed", exc_info=True)
        sys.exit(1)


def clone_frappe_docker_repo():
    """Downloads and extracts the frappe_docker repository."""
    if os.path.exists("frappe_docker"):
        cprint("frappe_docker directory already exists.", level=3)
        return

    cprint("--- Downloading frappe_docker repository ---", level=2)
    try:
        urllib.request.urlretrieve(
            "https://github.com/frappe/frappe_docker/archive/refs/heads/main.zip",
            "frappe_docker.zip",
        )
        unpack_archive("frappe_docker.zip", ".")
        move("frappe_docker-main", "frappe_docker")
        os.remove("frappe_docker.zip")
        cprint("Successfully downloaded and extracted frappe_docker.", level=2)
    except Exception as e:
        cprint(f"Failed to download or extract frappe_docker repository: {e}", level=1)
        logging.error("Download and unzip failed", exc_info=True)
        sys.exit(1)

def install_docker():
    cprint("Docker is not installed. Attempting installation...", level=3)
    if platform.system() != "Linux":
        cprint("This script can only auto-install Docker on Linux.", level=1)
        cprint("Please install Docker Desktop for your OS and re-run this script.", level=1)
        sys.exit(1)
    try:
        run_command(["curl", "-fsSL", "https://get.docker.com", "-o", "get-docker.sh"])
        run_command(["sudo", "sh", "get-docker.sh"])
        run_command(["sudo", "usermod", "-aG", "docker", os.getenv("USER")])
        os.remove("get-docker.sh")
        cprint("Docker installed successfully. You may need to log out and log back in for group changes to take effect.", level=2)
        cprint("Please re-run the script after logging back in.", level=3)
        sys.exit(0)
    except Exception as e:
        cprint(f"Failed to install Docker: {e}", level=1)
        cprint("Please try installing Docker manually and re-run this script.", level=3)
        sys.exit(1)

def check_dependencies():
    """Checks for Docker and Docker Compose, and clones the repo."""
    if not which("docker"):
        install_docker()
    if not which("docker-compose"):
        cprint("Docker Compose V1 is not found. Please ensure Docker Desktop or Docker Engine with the Compose plugin is installed.", level=1)
        cprint("See: https://docs.docker.com/compose/install/", level=3)
        sys.exit(1)
    clone_frappe_docker_repo()


def get_compose_files(args):
    """Assembles the list of Docker Compose files based on arguments."""
    compose_files = [
        "-f", "compose.yaml",
        "-f", "overrides/compose.mariadb.yaml",
        "-f", "overrides/compose.redis.yaml"
    ]
    if hasattr(args, 'no_ssl') and args.no_ssl:
        compose_files.extend(["-f", "overrides/compose.noproxy.yaml"])
    else:
        compose_files.extend(["-f", "overrides/compose.proxy.yaml", "-f", "overrides/compose.https.yaml"])
    
    # Add backup cron job for deploy and upgrade
    if args.command in ['deploy', 'upgrade']:
        compose_files.extend(["-f", "overrides/compose.backup-cron.yaml"])

    return compose_files


def generate_pass(length: int = 12) -> str:
    """Generates a secure random password."""
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(length))


def prepare_environment(args):
    """Prepares environment variables and docker-compose.yml for deployment."""
    home_dir = os.path.expanduser("~")
    passwords_file = os.path.join(home_dir, f"{args.project_name}-passwords.txt")
    compose_file_path = os.path.join(home_dir, f"{args.project_name}-compose.yml")
    
    db_root_password = generate_pass()
    admin_password = generate_pass()

    with open(passwords_file, "w") as f:
        f.write(f"MARIADB_ROOT_PASSWORD: {db_root_password}\n")
        f.write(f"ADMINISTRATOR_PASSWORD: {admin_password}\n")
    cprint(f"Passwords saved to {passwords_file}", level=2)
    
    env = os.environ.copy()
    if hasattr(args, 'tag') and args.tag:
        image_name, image_tag = args.tag.split(':', 1) if ':' in args.tag else (args.tag, 'latest')
        env['CUSTOM_IMAGE'] = image_name
        env['CUSTOM_TAG'] = image_tag
    else:
        env['ERPNEXT_VERSION'] = args.version

    env['PULL_POLICY'] = 'missing'
    env['SITES'] = f"`{args.site_name}`"
    env['LETSENCRYPT_EMAIL'] = args.email
    env['DB_PASSWORD'] = db_root_password
    
    if hasattr(args, 'no_ssl') and args.no_ssl:
        env['HTTP_PUBLISH_PORT'] = str(args.http_port)

    compose_files = get_compose_files(args)
    config_command = ["docker-compose"] + compose_files + ["config"]
    final_compose_content = run_command(config_command, cwd="frappe_docker", env=env, capture_output=True)
    
    with open(compose_file_path, "w") as f:
        f.write(final_compose_content)
    cprint(f"Docker Compose configuration saved to {compose_file_path}", level=2)

    return compose_file_path, db_root_password, admin_password


# --- Command Functions ---

def build_image(args):
    check_dependencies()
    cprint(f"--- Building Custom Image: {args.tag} ---", level=2)
    if not os.path.exists(args.apps_json):
        cprint(f"Error: The file '{args.apps_json}' was not found.", level=1)
        sys.exit(1)

    with open(args.apps_json, 'r') as f:
        apps_json_base64 = base64.b64encode(f.read().encode('utf-8')).decode('utf-8')

    build_command = [
        "docker", "build",
        "--build-arg", f"FRAPPE_PATH={args.frappe_path}",
        "--build-arg", f"FRAPPE_BRANCH={args.frappe_branch}",
        "--build-arg", f"PYTHON_VERSION={args.python_version}",
        "--build-arg", f"NODE_VERSION={args.node_version}",
        "--build-arg", f"APPS_JSON_BASE64={apps_json_base64}",
        "--tag", args.tag,
        "--file", args.containerfile,
        "frappe_docker"
    ]
    run_command(build_command)
    cprint(f"--- Successfully built {args.tag} ---", level=2)
    if args.push:
        cprint(f"--- Pushing image {args.tag} to registry ---", level=2)
        run_command(["docker", "push", args.tag])
    if args.deploy:
        cprint("\n--- Build complete, proceeding to deployment ---", level=2)
        deploy_environment(args)

def deploy_environment(args):
    check_dependencies()
    cprint(f"--- Deploying Project: {args.project_name} ---", level=2)
    compose_file_path, db_pass, admin_pass = prepare_environment(args)
    
    run_command(["docker-compose", "-p", args.project_name, "-f", compose_file_path, "up", "-d"])
    cprint("--- Environment is starting up... This may take a few minutes. ---", level=3)
    time.sleep(90)

    cprint(f"--- Creating Site: {args.site_name} ---", level=2)
    site_command = [
        "docker-compose", "-p", args.project_name, "-f", compose_file_path, "exec", "backend", "bench",
        "new-site", args.site_name,
        "--mariadb-user-host-login-scope=%",
        "--db-root-password", db_pass,
        "--admin-password", admin_pass,
        "--set-default"
    ]
    
    install_apps_list = []
    if hasattr(args, 'apps_json') and args.apps_json and os.path.exists(args.apps_json):
        with open(args.apps_json, 'r') as f:
            apps = json.load(f)
            install_apps_list = [app['url'].split('/')[-1].replace('.git', '') for app in apps]
    elif hasattr(args, 'app') and args.app:
        install_apps_list = args.app.split(',')
        
    for app_name in install_apps_list:
        site_command.extend(["--install-app", app_name])

    run_command(site_command)
    cprint("\n--- Deployment Complete! ---", level=2)
    site_url = f"https://{args.site_name}" if not (hasattr(args, 'no_ssl') and args.no_ssl) else f"http://{args.site_name}"
    cprint(f"Your site '{args.site_name}' should be available at: {site_url}", level=2)
    cprint(f"Login with user 'Administrator' and the password from {os.path.expanduser('~')}/{args.project_name}-passwords.txt", level=3)

def upgrade_environment(args):
    check_dependencies()
    cprint(f"--- Upgrading Project: {args.project_name} ---", level=2)
    compose_file_path, _, _ = prepare_environment(args)

    cprint("--- Pulling new images... ---", level=3)
    run_command(["docker-compose", "-p", args.project_name, "-f", compose_file_path, "pull"])

    cprint("--- Recreating containers... ---", level=3)
    run_command(["docker-compose", "-p", args.project_name, "-f", compose_file_path, "up", "-d", "--force-recreate", "--remove-orphans"])

    cprint("--- Running database migrations... ---", level=3)
    migrate_command = [
        "docker-compose", "-p", args.project_name, "-f", compose_file_path, "exec", "backend", "bench",
        "--site", "all", "migrate"
    ]
    run_command(migrate_command)
    cprint("--- Upgrade Complete! ---", level=2)

def develop_environment(args):
    check_dependencies()
    cprint(f"--- Setting up Development Environment for Project: {args.project_name} ---", level=2)
    dev_compose_file = os.path.join("frappe_docker", "devcontainer-example", "docker-compose.yml")
    run_command(["docker-compose", "-p", args.project_name, "-f", dev_compose_file, "up", "-d"])
    cprint("--- Development containers are up! ---", level=2)
    cprint("For next steps, see the development documentation:", level=3)
    cprint("https://github.com/frappe/frappe_docker/blob/main/docs/development.md", level=3)

def exec_command(args):
    check_dependencies()
    cprint(f"--- Executing command in project: {args.project_name} ---", level=2)
    home_dir = os.path.expanduser("~")
    compose_file_path = os.path.join(home_dir, f"{args.project_name}-compose.yml")
    if not os.path.exists(compose_file_path):
        cprint(f"Compose file not found at {compose_file_path}. Cannot execute command.", level=1)
        sys.exit(1)
    
    command = [
        "docker-compose", "-p", args.project_name, "-f", compose_file_path, "exec", "backend"
    ] + args.cmd
    run_command(command)

def main():
    parser = argparse.ArgumentParser(description="Easy Install script for Frappe Docker environments.", formatter_class=argparse.RawTextHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Build Command ---
    parser_build = subparsers.add_parser("build", help="Build a custom Frappe Docker image.")
    parser_build.add_argument("-j", "--apps-json", required=True, help="Path to apps.json file")
    parser_build.add_argument("-t", "--tag", default="custom-apps:latest", help="Tag for the custom image")
    parser_build.add_argument("-p", "--push", action='store_true', help="Push the built image to registry")
    parser_build.add_argument("-r", "--frappe-path", default="https://github.com/frappe/frappe", help="Frappe repository to use")
    parser_build.add_argument("-b", "--frappe-branch", default="version-15", help="Frappe branch to use")
    parser_build.add_argument("-c", "--containerfile", default="images/layered/Containerfile", help="Path to the Containerfile")
    parser_build.add_argument("-y", "--python-version", default="3.11.6", help="Python Version")
    parser_build.add_argument("-d", "--node-version", default="18.18.2", help="NodeJS Version")
    parser_build.add_argument("-x", "--deploy", action='store_true', help="Deploy environment after a successful build")
    parser_build.add_argument("-n", "--project-name", default="custom-project", help="Project Name for deployment")
    parser_build.add_argument("-s", "--site-name", default="localhost", help="Site Name for deployment")
    parser_build.add_argument("-e", "--email", default="test@example.com", help="Email for SSL certificate for deployment.")
    parser_build.add_argument("-q", "--no-ssl", action='store_true', help="Do not use HTTPS for deployment")
    parser_build.set_defaults(func=build_image)
    
    # --- Deploy Command ---
    parser_deploy = subparsers.add_parser("deploy", help="Deploy a Frappe environment.")
    parser_deploy.add_argument("-p", "--project-name", default="frappe-production", help="A unique name for the Docker Compose project")
    parser_deploy.add_argument("-s", "--site-name", required=True, help="The domain name for the new site")
    parser_deploy.add_argument("-e", "--email", required=True, help="Email address for Let's Encrypt SSL certificate registration.")
    parser_deploy.add_argument("-a", "--app", help="Comma-separated list of apps to install (e.g., erpnext,hrms)")
    parser_deploy.add_argument("-v", "--version", default='v15', help="ERPNext version for default image (e.g., v15)")
    parser_deploy.add_argument("-j", "--apps-json", help="Path to apps.json file (if using custom apps)")
    parser_deploy.add_argument("-t", "--tag", help="The tag of the custom image to deploy")
    parser_deploy.add_argument("-q", "--no-ssl", action='store_true', help="Deploy without HTTPS")
    parser_deploy.add_argument("-m", "--http-port", default=80, type=int, help="HTTP port to expose if not using SSL")
    parser_deploy.set_defaults(func=deploy_environment)

    # --- Upgrade Command ---
    parser_upgrade = subparsers.add_parser("upgrade", help="Upgrade an existing environment.")
    parser_upgrade.add_argument("-p", "--project-name", required=True, help="Name of the project to upgrade.")
    parser_upgrade.add_argument("-v", "--version", help="The new ERPNext or image version to upgrade to.")
    parser_upgrade.add_argument("-t", "--tag", help="The tag of the custom image to upgrade to.")
    parser_upgrade.set_defaults(func=upgrade_environment)

    # --- Develop Command ---
    parser_develop = subparsers.add_parser("develop", help="Set up a development environment.")
    parser_develop.add_argument("-p", "--project-name", default="frappe-dev", help="A unique name for the development project.")
    parser_develop.set_defaults(func=develop_environment)

    # --- Exec Command ---
    parser_exec = subparsers.add_parser("exec", help="Execute a command in the backend container.")
    parser_exec.add_argument("-p", "--project-name", required=True, help="Name of the project to execute command in.")
    parser_exec.add_argument("cmd", nargs=argparse.REMAINDER, help="The command to execute.")
    parser_exec.set_defaults(func=exec_command)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

