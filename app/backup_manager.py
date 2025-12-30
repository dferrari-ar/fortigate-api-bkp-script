import os
import time
import datetime
import logging
from logging.handlers import RotatingFileHandler
import requests
import schedule
import urllib3
import subprocess
import shutil
import urllib.parse

# Suppress insecure request warnings for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
CONFIG_DIR = "config"
BACKUP_DIR = "/backups"
DEVICES_FILE = os.path.join(CONFIG_DIR, "devices.txt")
GIT_SYNC_DIR = "/tmp/repo_sync"
#
# Logging Setup
debug_mode = os.environ.get("DEBUG", "no").lower() == "yes"
log_level = logging.DEBUG if debug_mode else logging.INFO

log_file = os.path.join(BACKUP_DIR, "logs", "backup.log")
os.makedirs(os.path.dirname(log_file), exist_ok=True)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5)
    ]
)
logger = logging.getLogger(__name__)

# If debug, enable requests logging
if debug_mode:
    # These loggers are very verbose
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("requests").setLevel(logging.DEBUG)
else:
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

def get_env_var(name, default=None):
    return os.environ.get(name, default)

def load_devices():
    devices = []
    if os.path.exists(DEVICES_FILE):
        with open(DEVICES_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Parse "IP:PORT, Name" or just "IP:PORT"
                    parts = line.split(',')
                    connection_string = parts[0].strip()
                    name = parts[1].strip() if len(parts) > 1 else None
                    
                    devices.append({
                        "connection_string": connection_string,
                        "name": name
                    })
    return devices

def sanitize_name(name):
    # Sanitize name for filename/folder safety
    return "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(" ", "_")

def rotate_files(target_folder, extensions=(".conf", ".log")):
    """Delete files older than LOGROTATE_DAYS in the specified folder with given extensions."""
    try:
        days_str = get_env_var("LOGROTATE_DAYS", "30")
        days = int(days_str)
        if days <= 0: return

        cutoff_time = time.time() - (days * 86400)
        
        if not os.path.exists(target_folder): return

        for filename in os.listdir(target_folder):
            file_path = os.path.join(target_folder, filename)
            if os.path.isfile(file_path) and any(filename.endswith(ext) for ext in extensions):
                file_mtime = os.path.getmtime(file_path)
                if file_mtime < cutoff_time:
                    try:
                        os.remove(file_path)
                        logger.info(f"Rotated (Deleted) old file: {filename}")
                    except Exception as e:
                        logger.error(f"Error deleting old file {filename}: {e}")
    except Exception as e:
        logger.error(f"Error in File Rotation for {target_folder}: {e}")

def rotate_backups(device_folder):
    rotate_files(device_folder, extensions=(".conf",))

def git_push_backup(local_file_path, relative_folder_name, filename):
    """Clone repo, copy file, commit and push."""
    target_rel_path = os.path.join("backups", relative_folder_name, filename)
    git_sync_files([(local_file_path, target_rel_path)], f"Backup {relative_folder_name} - {filename}")

def git_sync_files(files_to_sync, commit_msg):
    """
    General purpose sync to Git.
    files_to_sync: list of tuples (local_full_path, repo_relative_path)
    """
    repo_url = get_env_var("GIT_REPO_URL")
    github_token = get_env_var("GIT_PUSH_TOKEN")
    
    if not repo_url or not github_token:
        if debug_mode: logger.debug("Git sync skipped: GIT_REPO_URL or GIT_PUSH_TOKEN missing.")
        return

    if "https://" not in repo_url:
        logger.error("GIT_REPO_URL must be HTTPS.")
        return
        
    auth_url = repo_url
    askpass_path = "/tmp/git_askpass.sh"
    with open(askpass_path, "w") as f:
        f.write("#!/bin/sh\n")
        f.write("echo \"$GIT_PASSWORD\"\n")
    os.chmod(askpass_path, 0o700)
    
    git_env = os.environ.copy()
    git_env["GIT_ASKPASS"] = askpass_path
    git_env["GIT_USERNAME"] = "x-access-token"
    git_env["GIT_PASSWORD"] = github_token
    git_env["GIT_TERMINAL_PROMPT"] = "0"

    git_name = get_env_var("GIT_USER_NAME", "FortiBackup Bot")
    git_email = get_env_var("GIT_USER_EMAIL", "bot@backup.local")

    try:
        if os.path.exists(GIT_SYNC_DIR):
            shutil.rmtree(GIT_SYNC_DIR)
        
        logger.info(f"Git: Cloning repository for {commit_msg}...")
        subprocess.run(["git", "clone", "--depth", "1", auth_url, GIT_SYNC_DIR], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=git_env)
        
        subprocess.run(["git", "config", "user.name", git_name], cwd=GIT_SYNC_DIR, check=True, env=git_env)
        subprocess.run(["git", "config", "user.email", git_email], cwd=GIT_SYNC_DIR, check=True, env=git_env)
        
        for local_file, repo_rel_path in files_to_sync:
            target_file = os.path.join(GIT_SYNC_DIR, repo_rel_path)
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            shutil.copy2(local_file, target_file)
        
        subprocess.run(["git", "add", "-f", "--all"], cwd=GIT_SYNC_DIR, check=True, env=git_env)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=GIT_SYNC_DIR, capture_output=True, text=True)
        
        if status.stdout.strip():
            logger.info(f"Git: Committing changes for {commit_msg}...")
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=GIT_SYNC_DIR, check=True, env=git_env)
            subprocess.run(["git", "push"], cwd=GIT_SYNC_DIR, check=True, env=git_env)
            logger.info(f"Git: Sync successful ({commit_msg})")
        else:
            if debug_mode: logger.debug(f"Git: No changes to commit for {commit_msg}")
        
    except Exception as e:
        logger.error(f"Git Sync Error during '{commit_msg}': {e}")
    finally:
        if os.path.exists(GIT_SYNC_DIR):
            shutil.rmtree(GIT_SYNC_DIR)
        if os.path.exists(askpass_path):
            os.remove(askpass_path)

def backup_device(device_info):
    """Returns (Success Boolean, Message String)"""
    device_string = device_info["connection_string"]
    device_name = device_info["name"]
    display_name = device_name if device_name else device_string
    
    default_port = get_env_var("FGT_PORT", "443")
    protocol = get_env_var("FGT_PROTOCOL", "https")
    
    # Check if device_string is IP:PORT
    if ":" in device_string:
        ip, specific_port = device_string.split(":", 1)
        port = specific_port
        logger.info(f"Using specific port {port} for {ip}")
    else:
        ip = device_string
        port = default_port
    
    base_url = f"{protocol}://{ip}:{port}"
    
    # Construct Backup URL with encryption if requested
    # Robust check: strip whitespace, handle None
    encrypt_var = get_env_var("ENCRYPT_BACKUP", "no")
    encrypt_backup = str(encrypt_var).strip().lower() == "yes"
    
    if debug_mode:
        logger.debug(f"DEBUG: ENCRYPT_BACKUP env var is '{encrypt_var}' -> Enabled: {encrypt_backup}")

    encryption_key = get_env_var("BACKUP_ENCRYPTION_KEY")
    
    backup_endpoint = "/api/v2/monitor/system/config/backup?scope=global"
    
    if encrypt_backup:
        if not encryption_key:
            error_msg = f"Encryption requested for {ip} but BACKUP_ENCRYPTION_KEY is missing. Aborting."
            logger.error(error_msg)
            return False, error_msg
        
        # URL encode the encryption key to handle special characters safely
        encoded_password = urllib.parse.quote(encryption_key)
        backup_url = f"{base_url}{backup_endpoint}&options=encrypt&password={encoded_password}"
        logger.info(f"Encryption ENABLED for {ip} (Key provided and encoded)")
    else:
        backup_url = f"{base_url}{backup_endpoint}"
    
    # Determine credentials for this device
    # Priority 1: Check for Name-based token: "Forti-Lab" -> "Forti-Lab_Token"
    device_token = None
    token_var_name = None
    
    if device_name:
        # Format A (Name-based): Device Name "Forti-Lab" -> Env Var "FORTIGATE_API_TOKEN_FORTI_LAB"
        # We normalize to UPPERCASE to avoid case-sensitivity issues between Github Secrets and names.
        safe_env_name = device_name.replace(" ", "_").upper()
        token_var_name = f"FORTIGATE_API_TOKEN_{safe_env_name}"
        device_token = get_env_var(token_var_name)
    
    # Priority 2: Check for IP-based token (Fallback): FORTIGATE_API_TOKEN_192_168_1_1
    if not device_token:
        sanitized_ip = ip.replace(".", "_").replace(":", "_")
        fallback_var_name = f"FORTIGATE_API_TOKEN_{sanitized_ip}"
        
        # Check specific IP token
        ip_token = get_env_var(fallback_var_name)
        if ip_token:
            device_token = ip_token
            token_var_name = fallback_var_name

    # Priority 3: Global token
    global_token = get_env_var("FORTIGATE_API_TOKEN")
    
    token = device_token if device_token else global_token

    session = requests.Session()
    session.verify = False 
    
    try:
        display_name = device_name if device_name else ip
        
        if not token:
             error_msg = f"Authentication Failed: No API Token found for {display_name}. (Checked '{token_var_name}' and 'FORTIGATE_API_TOKEN')"
             logger.error(error_msg)
             return False, error_msg

        logger.info(f"Using API Token for {ip} (Source: {'Device-Specific' if device_token else 'Global'})")
        if debug_mode:
            logger.debug(f"DEBUG: Auth Header set to 'Bearer {token[:4]}***{token[-4:]}'")
            logger.debug(f"DEBUG: Connection details: URL={backup_url}, Verify=False")
        
        session.headers.update({'Authorization': f'Bearer {token}'})

        # 2. Download Backup
        logger.info(f"Starting backup download from {display_name} ({ip})...")

        # Note: requests sometimes needs stream=True for files
        backup_response = session.get(backup_url, stream=True, timeout=60)
        
        if backup_response.status_code == 200:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Determine Folder Name
            safe_folder_name = sanitize_name(device_name) if device_name else ip.replace(":", "_")
            
            # Create Device Specific Folder
            device_dir = os.path.join(BACKUP_DIR, safe_folder_name)
            os.makedirs(device_dir, exist_ok=True)
            
            # Determine Filename
            filename = f"{safe_folder_name}_config_{timestamp}.conf"
            filepath = os.path.join(device_dir, filename)
            
            with open(filepath, 'wb') as f:
                for chunk in backup_response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            logger.info(f"Backup successful for {display_name}: {filepath}")
            
            # Perform Local Log Rotation
            rotate_backups(device_dir)
            
            # Sync to Git (if configured)
            git_push_backup(filepath, safe_folder_name, filename)
            return True, "Backup Successful"
            
        else:
            error_msg = f"Failed to retrieve config for {ip}. Status: {backup_response.status_code}. Content: {backup_response.text[:100]}"
            logger.error(error_msg)
            return False, error_msg

    except Exception as e:
        error_msg = f"Exception during backup of {ip}: {e}"
        logger.error(error_msg)
        return False, error_msg
    finally:
        session.close()

def run_backup_job():
    logger.info("Starting backup job...")
    devices = load_devices()
    if not devices:
        logger.warning("No devices found in devices.txt")
        return

    results = []
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for device in devices:
        name = device["name"] if device["name"] else device["connection_string"]
        success, msg = backup_device(device)
        status = "✅ SUCCESS" if success else f"❌ FAILED: {msg}"
        results.append(f"{name} - {status}")

    # Generate and Sync Summary Log
    timestamp_file = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_content = f"Backup Job Summary - {timestamp}\n" + "="*40 + "\n" + "\n".join(results) + "\n"
    
    logs_dir = os.path.join(BACKUP_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    summary_path = os.path.join(logs_dir, f"summary_{timestamp_file}.log")
    
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_content)
    
    logger.info("Backup job finished. Syncing summary to Git...")
    git_sync_files([(summary_path, f"backups/logs/summary_{timestamp_file}.log")], f"Run Summary - {timestamp}")
    
    # Rotate summary logs room
    rotate_files(logs_dir, extensions=(".log",))

def main():
    logger.info("Fortigate Backup Service Started")
    
    run_mode = get_env_var("RUN_MODE", "manual").lower()
    schedule_time = get_env_var("SCHEDULE_TIME", "03:00")
    
    if run_mode == "schedule":
        logger.info(f"Running in SCHEDULE mode. Job scheduled for {schedule_time} daily.")
        schedule.every().day.at(schedule_time).do(run_backup_job)
        
        # Keep alive
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        logger.info("Running in MANUAL mode (run once).")
        run_backup_job()
        
if __name__ == "__main__":
    main()
