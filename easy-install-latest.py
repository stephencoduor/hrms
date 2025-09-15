import argparse
import subprocess
import sys
import os
import re
import math
import secrets

# This template is a direct adaptation of the user's provided, working docker-compose file.
# It integrates our automated password and site-creation logic into that stable architecture.
DOCKER_COMPOSE_TEMPLATE = """
name: {{PROJECT_NAME}}

services:
  configurator:
    image: {{APP_IMAGE}}
    restart: "no"
    entrypoint: [ "bash", "-c" ]
    command:
      - |
        bench set-config -g db_host db;
        bench set-config -gp db_port 3306;
        bench set-config -g redis_cache "redis://redis-cache:6379";
        bench set-config -g redis_queue "redis://redis-queue:6379";
        bench set-config -g redis_socketio "redis://redis-queue:6379";
        bench set-config -gp socketio_port 9000;
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    depends_on:
      db: { condition: service_healthy, required: true }
      redis-cache: { condition: service_started, required: true }
      redis-queue: { condition: service_started, required: true }
    networks:
      - {{PROJECT_NAME}}_network

  create-site:
    image: {{APP_IMAGE}}
    restart: "no"
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    depends_on:
      configurator: { condition: service_completed_successfully, required: true }
    entrypoint: [ "bash", "-c" ]
    command:
      - |
        if [ ! -f "sites/.site_created" ]; then
          echo "Site not found. Performing first-time site installation...";
          bench new-site {{SITE_NAME}} \\
            --db-root-password "{{DB_ROOT_PASSWORD}}" \\
            --admin-password "{{ADMIN_PASSWORD}}" \\
            --install-app hrms \\
            --set-default;
          if [ $? -eq 0 ]; then
            echo "Installation successful. Creating flag file.";
            touch sites/.site_created;
          else
            echo "Installation failed. Please check logs.";
            exit 1;
          fi
        else
          echo "Site already exists. Skipping installation.";
        fi
        echo "Finalizing: Synchronizing database password for site {{SITE_NAME}}...";
        bench --site {{SITE_NAME}} set-config db_password "{{DB_ROOT_PASSWORD}}";
    networks:
      - {{PROJECT_NAME}}_network

  backend:
    image: {{APP_IMAGE}}
    restart: unless-stopped
    depends_on:
      create-site: { condition: service_completed_successfully, required: true }
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    environment:
      - SITES={{SITE_NAME}}
      - MYSQL_ROOT_PASSWORD={{DB_ROOT_PASSWORD}}
      - MARIADB_ROOT_PASSWORD={{DB_ROOT_PASSWORD}}
      - DB_HOST=db
      - DB_PORT=3306
    networks:
      - {{PROJECT_NAME}}_network

  frontend:
    image: {{APP_IMAGE}}
    restart: unless-stopped
    command: [ "nginx-entrypoint.sh" ]
    environment:
      - BACKEND=backend:8000
      - SOCKETIO=websocket:9000
      - FRAPPE_SITE_NAME_HEADER={{SITE_NAME}}
      - UPSTREAM_REAL_IP_ADDRESS=127.0.0.1
      - UPSTREAM_REAL_IP_HEADER=X-Forwarded-For
      - UPSTREAM_REAL_IP_RECURSIVE="off"
      - PROXY_READ_TIMEOUT=120
      - CLIENT_MAX_BODY_SIZE=50m
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.frontend-http.rule=Host(`{{SITE_NAME}}`)"
      - "traefik.http.routers.frontend-http.entrypoints=websecure"
      - "traefik.http.routers.frontend-http.tls.certresolver=main-resolver"
      - "traefik.http.services.frontend.loadbalancer.server.port=8080"
    depends_on:
      backend: { condition: service_started, required: true }
      websocket: { condition: service_started, required: true }
    networks:
      - {{PROJECT_NAME}}_network

  proxy:
    image: traefik:v2.11
    restart: unless-stopped
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.main-resolver.acme.httpchallenge=true"
      - "--certificatesresolvers.main-resolver.acme.httpchallenge.entrypoint=web"
      - "--certificatesresolvers.main-resolver.acme.email={{LETSENCRYPT_EMAIL}}"
      - "--certificatesresolvers.main-resolver.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - cert-data:/letsencrypt
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - {{PROJECT_NAME}}_network

  queue-long:
    image: {{APP_IMAGE}}
    restart: unless-stopped
    command: [ "bench", "worker", "--queue", "long,default,short" ]
    depends_on:
      create-site: { condition: service_completed_successfully, required: true }
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    networks:
      - {{PROJECT_NAME}}_network

  queue-short:
    image: {{APP_IMAGE}}
    restart: unless-stopped
    command: [ "bench", "worker", "--queue", "short,default" ]
    depends_on:
      create-site: { condition: service_completed_successfully, required: true }
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    networks:
      - {{PROJECT_NAME}}_network

  redis-cache:
    image: redis:6.2-alpine
    restart: unless-stopped
    volumes:
      - redis-cache-data:/data
    networks:
      - {{PROJECT_NAME}}_network

  redis-queue:
    image: redis:6.2-alpine
    restart: unless-stopped
    volumes:
      - redis-queue-data:/data
    networks:
      - {{PROJECT_NAME}}_network

  scheduler:
    image: {{APP_IMAGE}}
    restart: unless-stopped
    command: [ "bench", "schedule" ]
    depends_on:
      create-site: { condition: service_completed_successfully, required: true }
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    networks:
      - {{PROJECT_NAME}}_network

  cron:
    image: mcuadros/ofelia:latest
    command: [ "daemon", "--docker" ]
    restart: unless-stopped
    depends_on:
      scheduler: { condition: service_started, required: true }
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    labels:
      - "ofelia.enabled=true"
      - "ofelia.job-exec.backup.schedule=@every 6h"
      - "ofelia.job-exec.backup.command=docker compose -p {{PROJECT_NAME}} exec -u frappe scheduler bench --site all backup"
      - "ofelia.job-exec.backup.user=frappe"
    networks:
      - {{PROJECT_NAME}}_network

  websocket:
    image: {{APP_IMAGE}}
    restart: unless-stopped
    command: [ "node", "/home/frappe/frappe-bench/apps/frappe/socketio.js" ]
    depends_on:
      create-site: { condition: service_completed_successfully, required: true }
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - sites-assets:/home/frappe/frappe-bench/sites/assets
    networks:
      - {{PROJECT_NAME}}_network

  db:
    image: mariadb:10.6
    restart: unless-stopped
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --skip-character-set-client-handshake
      - --skip-innodb-read-only-compressed
    environment:
      - MYSQL_ROOT_PASSWORD={{DB_ROOT_PASSWORD}}
    volumes:
      - db-data:/var/lib/mysql
    healthcheck:
      test: [ "CMD-SHELL", "mysqladmin ping -h localhost --password={{DB_ROOT_PASSWORD}}" ]
      interval: 1s
      retries: 20
    networks:
      - {{PROJECT_NAME}}_network

networks:
  {{PROJECT_NAME}}_network:
    name: {{PROJECT_NAME}}_network
    driver: bridge

volumes:
  sites:
    name: {{PROJECT_NAME}}_sites
  logs:
    name: {{PROJECT_NAME}}_logs
  db-data:
    name: {{PROJECT_NAME}}_db-data
  redis-queue-data:
    name: {{PROJECT_NAME}}_redis-queue-data
  redis-cache-data:
    name: {{PROJECT_NAME}}_redis-cache-data
  cert-data:
    name: {{PROJECT_NAME}}_cert-data
  sites-assets:
    name: {{PROJECT_NAME}}_sites-assets
"""

def run_command(command, quiet=False):
    """Executes a shell command and streams its output."""
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE if not quiet else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if not quiet else subprocess.DEVNULL,
            text=True
        )
        if not quiet:
            for line in iter(process.stdout.readline, ''):
                print(line, end='')
        process.wait()
        if process.returncode != 0:
            if not quiet:
                print(f"\\nError: Command failed with exit code {process.returncode}")
            return False
    except FileNotFoundError:
        if not quiet:
            print(f"Error: Command not found. Is Docker installed and in your PATH?")
        return False
    except Exception as e:
        if not quiet:
            print(f"An unexpected error occurred: {e}")
        return False
    return True

def generate_pass(length: int = 16) -> str:
    """Generate random hash using best available randomness source."""
    return secrets.token_hex(math.ceil(length / 2))[:length]

def get_passwords(project_name):
    """
    Gets passwords from the project's password file.
    If the file doesn't exist, it generates new passwords and saves them.
    """
    password_file = f"{project_name}-passwords.txt"
    passwords = {}

    if not os.path.exists(password_file):
        print(f"Password file '{password_file}' not found. Generating new secure passwords...")
        admin_pass = generate_pass()
        db_pass = generate_pass()
        
        content = [
            "# This file contains the auto-generated passwords for your deployment.\n",
            "# Keep this file safe. It will be re-used on subsequent deployments.\n\n",
            f"ADMIN_PASSWORD={admin_pass}\n",
            f"DB_ROOT_PASSWORD={db_pass}\n"
        ]
        
        try:
            with open(password_file, 'w') as f:
                f.writelines(content)
            print(f"Successfully generated and saved new passwords in '{password_file}'.")
            passwords['ADMIN_PASSWORD'] = admin_pass
            passwords['DB_ROOT_PASSWORD'] = db_pass
        except IOError as e:
            print(f"Error writing to password file '{password_file}': {e}")
            sys.exit(1)
    else:
        print(f"Reading passwords from existing file: '{password_file}'...")
        try:
            with open(password_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    try:
                        key, value = line.split('=', 1)
                        passwords[key.strip()] = value.strip()
                    except ValueError:
                        print(f"Warning: Skipping malformed line in password file: {line}")
        except IOError as e:
            print(f"Error reading password file '{password_file}': {e}")
            sys.exit(1)

    required_keys = ["ADMIN_PASSWORD", "DB_ROOT_PASSWORD"]
    missing_keys = [key for key in required_keys if key not in passwords]
    if missing_keys:
        print(f"Error: The password file '{password_file}' is missing required keys: {', '.join(missing_keys)}")
        sys.exit(1)

    return passwords

def check_project_exists():
    """Checks if docker-compose.yml and .env exist."""
    if not os.path.exists("docker-compose.yml") or not os.path.exists(".env"):
        print("Error: Project configuration not found. Please run a command in the project directory.")
        sys.exit(1)

def deploy(args):
    """Generates the docker-compose.yml file and starts the services."""
    sanitized_sitename = re.sub(r'[^a-zA-Z0-9_.-]', '', args.sitename).replace('.', '_')
    project_name = args.project_name or sanitized_sitename
    
    print(f"Using project name: {project_name}")

    passwords = get_passwords(project_name)
    admin_password = passwords['ADMIN_PASSWORD']
    db_root_password = passwords['DB_ROOT_PASSWORD']
    
    print("\\nGenerating docker-compose.yml and .env file...")
    content = DOCKER_COMPOSE_TEMPLATE
    content = content.replace("{{PROJECT_NAME}}", project_name)
    content = content.replace("{{APP_IMAGE}}", args.app)
    content = content.replace("{{SITE_NAME}}", args.sitename)
    content = content.replace("{{LETSENCRYPT_EMAIL}}", args.email)
    content = content.replace("{{DB_ROOT_PASSWORD}}", db_root_password)
    content = content.replace("{{ADMIN_PASSWORD}}", admin_password)

    try:
        with open("docker-compose.yml", "w") as f:
            f.write(content)
        with open(".env", "w") as f:
            f.write(f"COMPOSE_PROJECT_NAME={project_name}")
        print("Configuration files created successfully.")
    except IOError as e:
        print(f"Error writing configuration files: {e}")
        sys.exit(1)

    print("\\nStarting Docker services...")
    if not run_command("sudo docker compose up -d"):
        sys.exit(1)
    print("\\nDeployment complete!")

def destroy(args):
    """Stops services and removes all associated data."""
    check_project_exists()
    print("This will stop all services and permanently delete all associated volumes (data).")
    confirm = input("Are you sure you want to continue? [y/N]: ")
    if confirm.lower() != 'y':
        print("Operation cancelled.")
        return

    print("\\nStopping services and removing volumes...")
    if not run_command("sudo docker compose down -v"):
        sys.exit(1)
    print("\\nEnvironment destroyed.")

def down(args):
    """Stops and removes the containers without deleting data."""
    check_project_exists()
    print("\\nStopping and removing containers...")
    if not run_command("sudo docker compose down"):
        sys.exit(1)
    print("\\nServices are down. Your data is preserved in the volumes.")

def restart(args):
    """Restarts all the running services."""
    check_project_exists()
    print("\\nRestarting all services...")
    if not run_command("sudo docker compose restart"):
        sys.exit(1)
    print("\\nServices restarted.")

def main():
    """Main function to parse arguments and call appropriate handlers."""
    parser = argparse.ArgumentParser(
        description="Easy deployment script for HRMS on Docker.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy_parser = subparsers.add_parser("deploy", help="Deploy or restart the HRMS application.")
    deploy_parser.add_argument("--sitename", required=True, help="Domain name for the site (e.g., fineract.us).")
    deploy_parser.add_argument("--project-name", help="A unique name for this project. Defaults to a sanitized version of the sitename.")
    deploy_parser.add_argument("--email", required=True, help="Email for Let's Encrypt SSL certificate.")
    deploy_parser.add_argument("--app", required=True, help="The custom Docker image to use (e.g., custom/hrms:3.0).")
    deploy_parser.set_defaults(func=deploy)

    destroy_parser = subparsers.add_parser("destroy", help="Stop services and PERMANENTLY delete all data.")
    destroy_parser.set_defaults(func=destroy)
    
    down_parser = subparsers.add_parser("down", help="Stop and remove the running containers (data is preserved).")
    down_parser.set_defaults(func=down)

    restart_parser = subparsers.add_parser("restart", help="Restart all running services.")
    restart_parser.set_defaults(func=restart)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

