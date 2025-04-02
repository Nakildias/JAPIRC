import socket
import threading
import json
import hashlib
import datetime
import time
import os
import sys
from colored import fg, attr # Keep for server-side coloring

# --- Server Configuration ---
HOST = "0.0.0.0"
PORT = 5050 # Make sure this matches the client's default
USER_CREDENTIALS_FILE = "user_credentials.json"
OPS_FILE = "ops.json"  # File to store operators
SERVER_PASSWORD = "SuperSecret"  # Change this to your desired server password
SERVER_NAME = "MyIRCServer"  # Change this to your desired server name
FILE_DIRECTORY = "user_uploaded_files"  # Base directory for uploads

# --- NEW: User Registration Control ---
ALLOW_USER_AUTHENTICATION = True # Set to True to allow registration, False to disable

# --- Utility Functions ---
def get_current_time():
    """Returns the current time formatted as HH:MM:SS"""
    return datetime.datetime.now().strftime("%X")

def color_text(text, color):
    """Applies color codes for server console output. Handles potential invalid colors."""
    try:
        valid_colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white',
                        'dark_gray', 'light_red', 'light_green', 'light_yellow', 'light_blue',
                        'light_magenta', 'light_cyan']
        if color in valid_colors or (isinstance(color, int) and 0 <= color <= 255):
            return f"{fg(color)}{text}{attr('reset')}"
        else:
            print(f"[Color Warning] Unrecognized color '{color}' used. Falling back to white.")
            return f"{fg('white')}{text}{attr('reset')}"
    except Exception as e:
        print(f"[Color Error] Error applying color '{color}': {e}. Falling back to plain text.")
        return text

def format_for_client(message, prefix="[Server]"):
    """Formats messages for sending to the client (no color)."""
    message_str = str(message) if not isinstance(message, str) else message
    current_time_str = datetime.datetime.now().strftime("%X")
    return f"{current_time_str} {prefix} {message_str}"

# --- File Handling ---
if not os.path.exists(FILE_DIRECTORY):
    try:
        os.makedirs(FILE_DIRECTORY)
        print(color_text(f"{get_current_time()} [Info] Created base file directory: {FILE_DIRECTORY}", "yellow"))
    except OSError as e:
        print(color_text(f"{get_current_time()} [FATAL ERROR] Could not create file directory '{FILE_DIRECTORY}': {e}", "red"))
        sys.exit(1)

def handle_upload(client_socket, filepath, username):
    """Handles file 'upload' (copying from server path) to user's directory."""
    user_dir = os.path.join(FILE_DIRECTORY, username)
    try:
        os.makedirs(user_dir, exist_ok=True)

        if not os.path.exists(filepath):
            client_socket.send(format_for_client(f"Source file '{os.path.basename(filepath)}' not found on server.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Upload Error] {username} requested non-existent source file: {filepath}", "red"))
            return

        if not os.path.isfile(filepath):
            client_socket.send(format_for_client(f"Source path '{os.path.basename(filepath)}' is not a file.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Upload Error] {username} requested source path is not a file: {filepath}", "red"))
            return

        filename = os.path.basename(filepath)
        dest_path = os.path.join(user_dir, filename)

        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if ".." in filename or any(char in filename for char in invalid_chars):
            client_socket.send(format_for_client("Invalid filename provided.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Upload Error] {username} attempted invalid filename: {filename}", "red"))
            return

        if os.path.exists(dest_path):
            client_socket.send(format_for_client(f"File '{filename}' already exists in your server directory. Upload failed.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Upload Error] {username} attempted to overwrite existing file: {filename}", "yellow"))
            return

        copied_bytes = 0
        with open(filepath, "rb") as src_file, open(dest_path, "wb") as dest_file:
            while (data := src_file.read(4096)):
                dest_file.write(data)
                copied_bytes += len(data)

        client_socket.send(format_for_client(f"File '{filename}' uploaded successfully to your server directory.", "[Info]").encode("utf-8"))
        broadcast(format_for_client(f"{username} uploaded a file.", "[Info]"), None)
        print(color_text(f"{get_current_time()} [Upload] {username} uploaded '{filename}' ({copied_bytes} bytes) successfully.", "green"))

    except PermissionError as e:
        client_socket.send(format_for_client(f"Server permission error during upload.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} [Upload Error] Permission denied for {username} ({filepath}): {str(e)}", "red"))
    except Exception as e:
        client_socket.send(format_for_client(f"Error uploading file: Check server logs.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} [Upload Error] Failed for {username} ({filepath}): {str(e)}", "red"))


def handle_download(client_socket, target_username, filename, requestor_username):
    """Handles sending a file from a user's directory to the requestor."""
    user_dir = os.path.join(FILE_DIRECTORY, target_username)
    filepath = os.path.join(user_dir, filename)

    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    if ".." in filename or any(char in filename for char in invalid_chars):
        client_socket.send(format_for_client("Invalid filename requested.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} [Download Error] {requestor_username} attempted invalid filename: {filename}", "red"))
        return

    try:
        abs_user_dir = os.path.abspath(user_dir)
        abs_filepath = os.path.abspath(filepath)

        if not abs_filepath.startswith(abs_user_dir):
            client_socket.send(format_for_client(f"Error: File access denied.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Download Error] {requestor_username} attempted directory traversal: {filename}", "red"))
            return

        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            client_socket.send(format_for_client(f"Error: File '{filename}' not found in {target_username}'s directory.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Download Error] {requestor_username} requested non-existent file: {target_username}/{filename}", "yellow"))
            return

        file_size = os.path.getsize(filepath)
        header = f"FILE_TRANSFER:{filename}:{file_size}"
        client_socket.send(header.encode("utf-8"))
        print(color_text(f"{get_current_time()} [Download] Sending '{filename}' ({file_size} bytes) from {target_username} to {requestor_username}.", "yellow"))

        time.sleep(0.1)

        bytes_sent = 0
        with open(filepath, "rb") as file:
            while True:
                data = file.read(4096)
                if not data:
                    break
                client_socket.sendall(data)
                bytes_sent += len(data)

        print(color_text(f"{get_current_time()} [Download] File '{filename}' ({bytes_sent} bytes) sent successfully to {requestor_username}.", "green"))

    except FileNotFoundError:
        client_socket.send(format_for_client(f"Error: File '{filename}' not found during read.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} [Download Error] File disappeared during download?: {target_username}/{filename}", "red"))
    except ConnectionAbortedError:
        print(color_text(f"{get_current_time()} [Download Info] Connection aborted by {requestor_username} during download of {filename}.", "yellow"))
    except ConnectionResetError:
        print(color_text(f"{get_current_time()} [Download Info] Connection reset by {requestor_username} during download of {filename}.", "yellow"))
    except Exception as e:
        client_socket.send(format_for_client(f"Error downloading file. Check server logs.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} [Download Error] Failed sending {filename} to {requestor_username}: {str(e)}", "red"))

def handle_list_files(client_socket, target_username, requestor_username):
    """Lists files in the specified user's upload directory and sends them back in FILE_LIST format."""
    user_dir = os.path.join(FILE_DIRECTORY, target_username)
    file_list_message_prefix = f"FILE_LIST:{target_username}:"
    files_str = ""

    try:
        if not os.path.exists(user_dir) or not os.path.isdir(user_dir):
            client_socket.send(file_list_message_prefix.encode("utf-8"))
            print(color_text(f"{get_current_time()} [Files] Directory not found for {target_username}, requested by {requestor_username}. Sent empty list.", "yellow"))
            return

        files = [f for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f)) and f]

        if not files:
            client_socket.send(file_list_message_prefix.encode("utf-8"))
            print(color_text(f"{get_current_time()} [Files] No files found for {target_username}, requested by {requestor_username}. Sent empty list.", "yellow"))
        else:
            files_str = ";".join(files)
            full_message = file_list_message_prefix + files_str
            client_socket.send(full_message.encode("utf-8"))
            print(color_text(f"{get_current_time()} [Files] Sent file list for {target_username} to {requestor_username} ({len(files)} files).", "green"))

    except PermissionError as e:
        error_msg = format_for_client(f"Server permission error listing files for {target_username}.", "[Error]")
        client_socket.send(error_msg.encode("utf-8"))
        print(color_text(f"{get_current_time()} [Files Error] Permission denied listing for {target_username} (requested by {requestor_username}): {str(e)}", "red"))
    except Exception as e:
        error_msg = format_for_client(f"Error retrieving file list for {target_username}. Check server logs.", "[Error]")
        client_socket.send(error_msg.encode("utf-8"))
        print(color_text(f"{get_current_time()} [Files Error] Failed listing for {target_username} (requested by {requestor_username}): {str(e)}", "red"))

# --- NEW: File Deletion Handling ---
def handle_delete_file(client_socket, username, command_parts):
    """Handles a request to delete a file."""
    global ops # Access global ops list
    is_op = False
    with lock: # Check OP status safely
        is_op = username in ops

    # --- Case 1: /delete <filename> (Delete own file) ---
    if len(command_parts) == 2:
        filename = command_parts[1]
        target_user = username # User wants to delete their own file
        print_prefix = f"[Delete Own]"
    # --- Case 2: /delete <target_user> <filename> (OP deletes other's file) ---
    elif len(command_parts) == 3:
        if not is_op:
            client_socket.send(format_for_client("Permission denied. Only Operators can delete other users' files.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} [Delete Attempt] Non-OP {username} tried to delete file from {command_parts[1]}", "red"))
            return
        target_user = command_parts[1]
        filename = command_parts[2]
        print_prefix = f"[Delete OP]"
    # --- Invalid format ---
    else:
        usage = "Usage: /delete <filename>  OR  /delete <target_user> <filename> (Operator only)"
        client_socket.send(format_for_client(usage, "[Usage]").encode("utf-8"))
        return

    # --- Validate filename ---
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    if ".." in filename or any(char in filename for char in invalid_chars):
        client_socket.send(format_for_client("Invalid filename provided.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} {print_prefix} {username} attempted invalid filename: {filename}", "red"))
        return

    # --- Construct path and attempt deletion ---
    user_dir = os.path.join(FILE_DIRECTORY, target_user)
    filepath = os.path.join(user_dir, filename)
    abs_user_dir = os.path.abspath(user_dir)
    abs_filepath = os.path.abspath(filepath)

    # Extra security check: Ensure path is within the intended user directory
    if not abs_filepath.startswith(abs_user_dir):
        client_socket.send(format_for_client("Error: File access denied (path violation).", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} {print_prefix} {username} attempted directory traversal delete: {filename}", "red"))
        return

    try:
        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            success_msg = f"File '{filename}' deleted successfully"
            if target_user != username: # Add context if OP deleted someone else's file
                success_msg += f" from user '{target_user}'s directory"
            success_msg += "."

            client_socket.send(format_for_client(success_msg, "[Info]").encode("utf-8"))
            print(color_text(f"{get_current_time()} {print_prefix} {username} deleted file '{target_user}/{filename}'.", "green"))
            # Optionally notify the owner if an OP deleted their file (might be noisy)
            # if is_op and target_user != username:
            #     target_sock = find_socket_by_username(target_user)
            #     if target_sock:
            #         try:
            #             target_sock.send(format_for_client(f"Operator '{username}' deleted your file: '{filename}'", "[Warning]").encode("utf-8"))
            #         except: pass
        else:
            client_socket.send(format_for_client(f"Error: File '{filename}' not found in '{target_user}'s directory.", "[Error]").encode("utf-8"))
            print(color_text(f"{get_current_time()} {print_prefix} {username} tried to delete non-existent file: {target_user}/{filename}", "yellow"))

    except PermissionError:
        client_socket.send(format_for_client(f"Server permission error deleting file '{filename}'.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} {print_prefix} Permission denied deleting {target_user}/{filename} for {username}", "red"))
    except Exception as e:
        client_socket.send(format_for_client(f"Error deleting file '{filename}'. Check server logs.", "[Error]").encode("utf-8"))
        print(color_text(f"{get_current_time()} {print_prefix} Failed deleting {target_user}/{filename} for {username}: {str(e)}", "red"))

# --- Credentials and Ops Management ---
def load_credentials():
    try:
        with open(USER_CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(color_text(f"{get_current_time()} [Info] Credentials file not found or invalid, starting fresh.", "yellow"))
        return {}

def save_credentials(credentials):
    try:
        with lock: # Ensure thread safety when writing
            # Make a copy to avoid modifying the dictionary while iterating/dumping if needed elsewhere
            credentials_copy = credentials.copy()
            with open(USER_CREDENTIALS_FILE, "w") as f:
                json.dump(credentials_copy, f, indent=4)
    except IOError as e:
        print(color_text(f"{get_current_time()} [Error] Could not save credentials file: {e}", "red"))
    except Exception as e:
         print(color_text(f"{get_current_time()} [Error] Unexpected error saving credentials: {e}", "red"))


def load_ops():
    try:
        with open(OPS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(color_text(f"{get_current_time()} [Info] Ops file not found or invalid, starting with no operators.", "yellow"))
        return []

def save_ops(ops_list):
    try:
        with lock: # Ensure thread safety when writing
            # Make a copy to avoid issues if list is modified elsewhere during save
            ops_copy = ops_list[:]
            with open(OPS_FILE, "w") as f:
                json.dump(ops_copy, f, indent=4)
    except IOError as e:
        print(color_text(f"{get_current_time()} [Error] Could not save ops file: {e}", "red"))
    except Exception as e:
         print(color_text(f"{get_current_time()} [Error] Unexpected error saving ops: {e}", "red"))


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- Global Variables ---
user_credentials = load_credentials()
ops = load_ops()
clients = {} # {client_socket: username}
lock = threading.RLock() # RE-ENTRANT Lock for synchronizing access to shared resources
server_socket = None # Will be initialized in server()

# --- Client Handling Logic ---
def handle_client(client_socket, username):
    """Handles messages and commands from a single connected client."""
    print(color_text(f"{get_current_time()} [Thread] Started handler thread for {username}.", "blue"))
    while True:
        try:
            message_bytes = client_socket.recv(2048)
            if not message_bytes:
                print(color_text(f"{get_current_time()} [Connection] Received empty data from {username}, assuming disconnect.", "yellow"))
                break

            try:
                message = message_bytes.decode("utf-8")
            except UnicodeDecodeError:
                print(color_text(f"{get_current_time()} [Error] Received non-UTF8 data from {username}. Disconnecting.", "red"))
                try: client_socket.send(format_for_client("Invalid data received. Disconnecting.", "[Error]").encode("utf-8"))
                except: pass
                break

            msg_content = message.strip()
            if not msg_content: continue

            # --- Command Handling ---
            if msg_content.startswith("/"):
                # Use split with max split 2 for commands like /kick user reason, /delete user file
                # For commands like /upload or /download, we might need the rest of the line
                # Let's parse based on command specifically
                command = msg_content.split(" ", 1)[0].lower()
                print(color_text(f"{get_current_time()} [Command] {username} issued: {msg_content}", "magenta"))

                # == File Commands ==
                if command == "/upload":
                    if len(msg_content.split(" ", 1)) < 2:
                         client_socket.send(format_for_client("Usage: /upload <server_source_filepath>", "[Usage]").encode("utf-8"))
                    else:
                         server_source_path = msg_content.split(" ", 1)[1] # Get everything after /upload
                         server_source_path = server_source_path.strip('"') # Basic quote stripping
                         print(color_text(f"{get_current_time()} [Debug] Calling handle_upload with server_source_path='{server_source_path}'", "dark_gray"))
                         handle_upload(client_socket, server_source_path, username)

                elif command == "/download":
                    parts = msg_content.split(" ", 2) # /download user filename
                    if len(parts) < 3:
                         client_socket.send(format_for_client("Usage: /download <username> <filename>", "[Usage]").encode("utf-8"))
                    else:
                         target_user = parts[1]
                         filename = parts[2].strip('"') # Basic quote stripping
                         handle_download(client_socket, target_user, filename, username)

                elif command == "/files":
                    parts = msg_content.split(" ", 1) # /files username
                    if len(parts) < 2:
                        client_socket.send(format_for_client("Usage: /files <username>", "[Usage]").encode("utf-8"))
                    else:
                        target_user = parts[1]
                        handle_list_files(client_socket, target_user, username)

                # --- NEW: Delete Command ---
                elif command == "/delete":
                     # Need to handle potential spaces in filename if used with target user
                     # Split into parts: /delete [target_user] filename
                     # Let handle_delete_file figure it out based on number of parts
                     command_parts = msg_content.split(" ") # Simple space split for now
                     handle_delete_file(client_socket, username, command_parts)
                # --- End Delete Command ---

                # == Operator Commands ==
                elif command in ["/kick", "/stop", "/restart", "/listops", "/op", "/deop"]:
                    with lock:
                        is_op = username in ops
                    if not is_op:
                        client_socket.send(format_for_client("You do not have permission to execute this command.", "[Error]").encode("utf-8"))
                    else:
                        # Pass the raw message content for more flexible parsing inside handle_server_command
                        handle_server_command(client_socket, username, msg_content)

                # == General Commands ==
                elif command == "/list":
                    with lock:
                        user_list_sorted = sorted(list(clients.values()))
                        user_list_str = ", ".join(user_list_sorted)
                        num_users = len(clients)
                    client_socket.send(format_for_client(f"Connected users ({num_users}): {user_list_str}", "[Users]").encode("utf-8"))

                elif command == "/help":
                    # --- UPDATED Help Text ---
                    help_text = """
Available Commands:
  /help             Show this help message
  /list             List connected users
  /files <username> List files uploaded by a user
  /upload <path>    Upload a file (CURRENTLY COPIES FROM *SERVER* PATH - DOES NOT WORK FOR CLIENT UPLOAD)
  /download <user> <fn> Download a file from a user
  /delete <filename>    Delete one of your uploaded files
  /exit             Disconnect from the server

Operator Commands (require OP status):
  /kick <user> [reason] Kick a user
  /op <username>        Make a registered user an operator
  /deop <username>      Remove operator status from a user
  /listops          List current server operators
  /delete <user> <fn>   Delete a file from specified user (OP Only)
  /stop               Stop the server (console only recommended)
  /restart            Restart the server (console only recommended)
"""
                    client_socket.send(help_text.encode("utf-8")) # Send raw help text

                elif command == "/exit":
                    print(color_text(f"{get_current_time()} [Connection] {username} sent /exit command.", "yellow"))
                    break

                else:
                    client_socket.send(format_for_client(f"Unknown command: {command}", "[Error]").encode("utf-8"))

            # --- Regular Message Handling ---
            else:
                if len(msg_content) > 512:
                    print(color_text(f"{get_current_time()} {username} sent a message that is too long: {len(msg_content)} chars", "yellow"))
                    client_socket.send(format_for_client("Message cannot exceed 512 characters.", "[Error]").encode("utf-8"))
                    continue

                formatted_print_msg = f"{get_current_time()} [{color_text(username, 'cyan')}]: {msg_content}"
                print(formatted_print_msg) # Print to SERVER console with color

                formatted_broadcast_msg = format_for_client(f"{msg_content}", f"[{username}]")
                broadcast(formatted_broadcast_msg, client_socket) # Send to OTHER clients without color

        except ConnectionResetError:
            print(color_text(f"{get_current_time()} [Connection] Connection reset by {username}.", "yellow"))
            break
        except ConnectionAbortedError:
            print(color_text(f"{get_current_time()} [Connection] Connection aborted for {username}.", "yellow"))
            break
        except socket.timeout:
            print(color_text(f"{get_current_time()} [Connection] Socket timeout for {username}.", "yellow"))
            break
        except OSError as e:
            print(color_text(f"{get_current_time()} [Socket Error] OSError for {username}: {e}", "red"))
            break
        except Exception as e:
            print(color_text(f"{get_current_time()} [Error] Unexpected error handling client {username}: {e}", "red"))
            try:
                client_socket.send(format_for_client("An internal server error occurred.", "[Error]").encode("utf-8"))
            except: pass
            break

    # --- Disconnection Cleanup ---
    disconnected_user = None
    with lock:
        if client_socket in clients:
            disconnected_user = clients.pop(client_socket, None)

    if disconnected_user:
        print(color_text(f"{get_current_time()} [Disconnect] {disconnected_user} disconnected.", "red"))
        broadcast(format_for_client(f"{disconnected_user} has left the chat.", "[Info]"), None)
    else:
         # This might happen if disconnect occurred during login before username was assigned
         print(color_text(f"{get_current_time()} [Disconnect] A client disconnected but wasn't found in the active list (possibly during login or race condition).", "yellow"))

    try:
        # Try to use the username we retrieved if available, otherwise fallback
        log_username = disconnected_user if disconnected_user else 'unknown client'
        print(color_text(f"{get_current_time()} [Thread] Closing socket for {log_username}.", "blue"))
        client_socket.shutdown(socket.SHUT_RDWR)
        client_socket.close()
        print(color_text(f"{get_current_time()} [Thread] Socket closed for {log_username}.", "blue"))
    except OSError as e:
        log_username_err = disconnected_user if disconnected_user else 'unknown client'
        print(color_text(f"{get_current_time()} [Thread] Info: Non-critical error closing socket for {log_username_err}: {e} (Socket likely already closed)", "blue"))
    except Exception as e:
        log_username_err = disconnected_user if disconnected_user else 'unknown client'
        print(color_text(f"{get_current_time()} [Thread Error] Error closing socket for {log_username_err}: {e}", "red"))

    log_username_final = disconnected_user if disconnected_user else 'disconnected client'
    print(color_text(f"{get_current_time()} [Thread] Handler thread finished for {log_username_final}.", "blue"))


def handle_server_command(client_socket, issuer_username, message):
    """Handles commands that require operator privileges."""
    global ops, user_credentials # Ensure access to globals
    parts = message.split(" ", 2) # Split potentially including reason/filename
    command = parts[0].lower()
    kick_success = False # Flag specific to kick command
    broadcast_msg = ""   # Broadcast message specific to kick command
    op_changed = False   # Flag for op/deop success
    op_needs_save = False # Flag to indicate ops list was modified
    op_change_msg = "" # Message for op/deop issuer
    notify_target_sock = None # Socket of the user being opped/deopped
    notify_target_msg = "" # Message for the user being opped/deopped
    log_msg = ""           # Message for server log
    target_user = ""     # Define target_user outside conditional blocks

    # Use lock for commands modifying shared state (clients, ops, user_credentials read)
    with lock:
        if command == "/kick":
            # --- KICK LOGIC ---
            if len(parts) < 2:
                client_socket.send(format_for_client("Usage: /kick <username> [reason]", "[Usage]").encode("utf-8"))
                return

            target_user = parts[1]
            reason = parts[2] if len(parts) > 2 else "No reason specified."

            if target_user == issuer_username:
                client_socket.send(format_for_client("You cannot kick yourself.", "[Error]").encode("utf-8"))
                return

            target_socket_kick = None
            for sock, user in clients.items():
                if user == target_user:
                    target_socket_kick = sock
                    break

            if target_socket_kick:
                kick_message = format_for_client(f"You have been kicked by {issuer_username}. Reason: {reason}", "[Kick]")
                try:
                    target_socket_kick.send(kick_message.encode("utf-8"))
                    # Give a moment for the message to potentially send before shutting down
                    time.sleep(0.1)
                    target_socket_kick.shutdown(socket.SHUT_RDWR)
                except OSError as e:
                    print(color_text(f"{get_current_time()} [Kick Error] Error sending kick/shutting down socket for {target_user}: {e} (client may have already disconnected)", "red"))
                except Exception as e:
                    print(color_text(f"{get_current_time()} [Kick Error] Unexpected error during kick socket handling for {target_user}: {e}", "red"))
                finally:
                    # Ensure removal happens even if send/shutdown fails
                    clients.pop(target_socket_kick, None) # Use pop with default None
                    try:
                        target_socket_kick.close() # Attempt close as well
                    except: pass # Ignore errors closing already potentially broken socket

                kick_success = True # Set kick flag
                broadcast_msg = format_for_client(f"{target_user} was kicked by {issuer_username}. Reason: {reason}", "[Info]")
                log_msg = f"[Kick] {issuer_username} kicked {target_user}. Reason: {reason}" # Log message for outside lock

            else: # Target user not found
                client_socket.send(format_for_client(f"User '{target_user}' not found online.", "[Error]").encode("utf-8"))
                kick_success = False
            # --- END KICK LOGIC ---

        # --- NEW: OP LOGIC ---
        elif command == "/op":
            if len(parts) != 2:
                op_change_msg = format_for_client("Usage: /op <username>", "[Usage]")
            else:
                target_user = parts[1]
                if target_user == issuer_username:
                    op_change_msg = format_for_client("You cannot op yourself.", "[Error]")
                elif target_user not in user_credentials:
                    op_change_msg = format_for_client(f"User '{target_user}' does not exist (must be registered).", "[Error]")
                elif target_user in ops:
                    op_change_msg = format_for_client(f"User '{target_user}' is already an operator.", "[Info]")
                else:
                    ops.append(target_user)
                    # save_ops(ops) # Save the updated list - MOVED outside lock
                    op_needs_save = True # Mark for saving
                    op_changed = True
                    op_change_msg = format_for_client(f"User '{target_user}' is now an operator.", "[Info]")
                    log_msg = f"[OP] {issuer_username} opped {target_user}."
                    notify_target_msg = format_for_client(f"You have been promoted to Operator by {issuer_username}.", "[Info]")
                    # Find the target socket to notify (if online)
                    for sock, user in clients.items():
                        if user == target_user:
                            notify_target_sock = sock
                            break
        # --- END OP LOGIC ---

        # --- NEW: DEOP LOGIC ---
        elif command == "/deop":
            if len(parts) != 2:
                op_change_msg = format_for_client("Usage: /deop <username>", "[Usage]")
            else:
                target_user = parts[1]
                if target_user == issuer_username:
                    op_change_msg = format_for_client("You cannot deop yourself.", "[Error]")
                elif target_user not in ops:
                    op_change_msg = format_for_client(f"User '{target_user}' is not an operator.", "[Error]")
                else:
                    try:
                        ops.remove(target_user)
                        # save_ops(ops) # Save the updated list - MOVED outside lock
                        op_needs_save = True # Mark for saving
                        op_changed = True
                        op_change_msg = format_for_client(f"User '{target_user}' is no longer an operator.", "[Info]")
                        log_msg = f"[DEOP] {issuer_username} de-opped {target_user}."
                        notify_target_msg = format_for_client(f"Your Operator status has been removed by {issuer_username}.", "[Info]")
                        # Find the target socket to notify (if online)
                        for sock, user in clients.items():
                            if user == target_user:
                                notify_target_sock = sock
                                break
                    except ValueError:
                        # Should be rare because of the 'not in ops' check, but handle defensively
                        op_change_msg = format_for_client(f"Error: Could not remove '{target_user}' from operators list (internal state mismatch?).", "[Error]")
                        print(color_text(f"{get_current_time()} [DEOP Error] Attempted to remove {target_user} (requested by {issuer_username}), but they were not found in ops list during remove.", "red"))
                        op_changed = False # Ensure flags are consistent on error
                        op_needs_save = False
        # --- END DEOP LOGIC ---

        elif command == "/listops":
             # --- LISTOPS LOGIC (Existing) ---
             op_list_sorted = sorted(ops)
             op_list_str = ", ".join(op_list_sorted) if op_list_sorted else "No operators defined."
             client_socket.send(format_for_client(f"Current Operators: {op_list_str}", "[Ops]").encode("utf-8"))
             print(color_text(f"{get_current_time()} [Info] {issuer_username} listed operators.", "yellow"))
             # --- END LISTOPS LOGIC ---

        elif command == "/stop":
            # --- STOP LOGIC (Existing) ---
            print(color_text(f"{get_current_time()} [Shutdown] Server stop initiated by OP {issuer_username}.", "red"))
            broadcast(format_for_client(f"Server is shutting down NOW! (Issued by {issuer_username})", "[Warning]"), None)
            # Schedule shutdown slightly later to allow broadcast message to go out
            threading.Timer(0.5, shutdown_server).start()
            # --- END STOP LOGIC ---

        elif command == "/restart":
            # --- RESTART LOGIC (Existing) ---
            print(color_text(f"{get_current_time()} [Restart] Server restart initiated by OP {issuer_username}.", "red"))
            broadcast(format_for_client(f"Server is restarting NOW! (Issued by {issuer_username})", "[Warning]"), None)
            # Schedule restart slightly later
            threading.Timer(0.5, restart_server).start()
            # --- END RESTART LOGIC ---

         # Note: No 'else' needed here as the command validity was checked in handle_client

    # --- Actions performed outside the main lock ---

    # Save ops list if it was modified
    if op_needs_save:
        save_ops(ops) # Call save function which handles its own locking

    # Send kick broadcast message if kick was successful
    if kick_success and broadcast_msg:
        print(color_text(f"{get_current_time()} {log_msg}", "red")) # Log kick action
        broadcast(broadcast_msg, None) # Inform everyone

    # Send op/deop confirmation to issuer
    if op_change_msg:
        try:
            client_socket.send(op_change_msg.encode("utf-8"))
        except Exception as e:
             print(color_text(f"{get_current_time()} [Error] Failed to send op/deop confirmation to {issuer_username}: {e}", "yellow"))

    # Send notification to the target user if op/deop succeeded and they are online
    if op_changed and notify_target_sock and notify_target_msg:
        try:
            notify_target_sock.send(notify_target_msg.encode("utf-8"))
        except Exception as e:
             # Need to access target_user variable here, ensure it's defined
             # If op/deop logic ensures target_user is set when op_changed is True, this is fine.
             print(color_text(f"{get_current_time()} [Info] Could not notify {target_user if target_user else 'target user'} of status change: {e}", "yellow"))


    # Log op/deop action if successful
    if op_changed and log_msg:
         print(color_text(f"{get_current_time()} {log_msg}", "green" if command == "/op" else "yellow"))


def broadcast(message, sender_socket):
    """Sends a message (already formatted, no color) to all clients except the sender."""
    disconnected_sockets = []
    with lock:
        # Create a copy of the keys to iterate over, avoiding modification issues
        current_clients = list(clients.keys())

    for client in current_clients:
        if client == sender_socket: continue
        try:
            # Using sendall for potentially larger messages like broadcasts
            client.sendall(message.encode("utf-8"))
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            # Common errors indicating client disconnected abruptly
            # Retrieve username *before* potentially removing the socket
            temp_username = "Unknown (lookup failed)"
            with lock: # Briefly re-acquire lock for safe lookup
                temp_username = clients.get(client, 'Unknown (disconnected)')
            print(color_text(f"{get_current_time()} [Broadcast Info] Client {temp_username} disconnected during broadcast: {e}. Marking for removal.", "yellow"))
            disconnected_sockets.append(client)
        except Exception as e:
            # Log unexpected errors, but try to get username if possible (might fail if client gone)
            client_username = "Unknown (lookup failed)"
            with lock: # Briefly re-acquire lock for safe lookup
                 client_username = clients.get(client, 'Unknown (error)')
            print(color_text(f"{get_current_time()} [Broadcast Error] Unexpected error sending to client {client_username}: {e}. Marking for removal.", "red"))
            disconnected_sockets.append(client)

    # Cleanup disconnected sockets outside the iteration loop
    if disconnected_sockets:
        print(color_text(f"{get_current_time()} [Broadcast Cleanup] Found {len(disconnected_sockets)} disconnected sockets during broadcast.", "blue"))
        with lock:
            for sock in disconnected_sockets:
                if sock in clients: # Check if still exists before removing (e.g., handled by client thread already)
                    disconnected_user = clients.pop(sock, 'Unknown (cleanup)')
                    print(color_text(f"{get_current_time()} [Broadcast Cleanup] Removing disconnected client: {disconnected_user}", "yellow"))
                    try: sock.close() # Close socket during cleanup
                    except: pass # Ignore errors closing already broken socket
                else:
                    # Socket might have already been removed by its handler thread, just try closing
                    print(color_text(f"{get_current_time()} [Broadcast Cleanup] Socket already removed, attempting close anyway.", "blue"))
                    try: sock.close()
                    except: pass


# --- MODIFIED handle_login FUNCTION ---
def handle_login(client_socket, addr):
    """Handles the initial connection, authentication, and registration process."""
    global user_credentials, ops, clients, ALLOW_USER_AUTHENTICATION # Access globals

    username = None
    login_successful = False
    print(color_text(f"{get_current_time()} [Auth] Connection attempt from {addr}", "blue"))
    try:
        client_socket.send(b"Enter server password: ")
        client_socket.settimeout(30) # 30 second timeout for server password
        server_password_attempt = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()

        if server_password_attempt != SERVER_PASSWORD:
            client_socket.send("Incorrect server password.\n".encode("utf-8"))
            print(color_text(f"{get_current_time()} [Auth] Failed server password attempt from {addr}", "yellow"))
            client_socket.settimeout(None)
            return

        client_socket.send("Server password OK. Enter username: ".encode("utf-8"))
        client_socket.settimeout(60) # Allow more time for username/password/registration
        username = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()

        is_valid_username = (username and 1 <= len(username) <= 18 and
                             " " not in username and
                             all(c.isalnum() or c in ['_', '-'] for c in username))

        if not is_valid_username:
            client_socket.send("Username invalid (1-18 chars, alphanumeric, _, -).\n".encode("utf-8"))
            print(color_text(f"{get_current_time()} [Auth] Invalid username attempt from {addr}: '{username}'", "yellow"))
            client_socket.settimeout(None)
            return

        # Check if user exists or is already logged in within the lock
        with lock:
            if username in clients.values():
                client_socket.send("Username already logged in.\n".encode("utf-8"))
                print(color_text(f"{get_current_time()} [Auth] Duplicate login attempt from {addr} for user: '{username}'", "yellow"))
                client_socket.settimeout(None)
                return
            user_exists = username in user_credentials

        # --- Handle Existing User or Registration ---
        if user_exists:
            # --- Existing User Logic ---
            print(color_text(f"{get_current_time()} [Auth] User '{username}' exists, prompting for password.", "blue"))
            client_socket.send("Username OK. Enter password: ".encode("utf-8"))
            # Timeout still 60 seconds from username prompt
            password = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()
            client_socket.settimeout(None) # Reset timeout after receiving password

            hashed_password = hash_password(password)

            with lock:
                correct_password = user_credentials.get(username) == hashed_password

            if not correct_password:
                client_socket.send("Incorrect password.\n".encode("utf-8"))
                print(color_text(f"{get_current_time()} [Auth] Failed password for user {username} from {addr}", "yellow"))
                return # Exit handle_login

            # Password correct for existing user
            print(color_text(f"{get_current_time()} [Auth] Password correct for {username}.", "green"))
            login_successful = True
            client_socket.send("Login successful.\n".encode("utf-8"))
            # Proceed to post-login actions below

        else:
            # --- New User / Registration Logic ---
            print(color_text(f"{get_current_time()} [Auth] User '{username}' does not exist. Checking registration status.", "blue"))
            if not ALLOW_USER_AUTHENTICATION:
                client_socket.send("User registration is not enabled on this server.\n".encode("utf-8"))
                print(color_text(f"{get_current_time()} [Auth] Registration disabled, rejected new user '{username}' from {addr}", "yellow"))
                client_socket.settimeout(None)
                return # Exit handle_login

            # Registration is allowed, proceed
            print(color_text(f"{get_current_time()} [Auth] Registration enabled for new user '{username}'.", "yellow"))
            client_socket.send("Username not found. Enter password in format 'new_password:new_password' to register: ".encode("utf-8"))
            # Timeout still 60 seconds from username prompt
            reg_password_input = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()
            client_socket.settimeout(None) # Reset timeout after receiving password

            # Validate registration password format
            password_parts = reg_password_input.split(':')
            if len(password_parts) == 2 and password_parts[0] and password_parts[0] == password_parts[1]:
                # Format is correct, passwords match, and are not empty
                new_password = password_parts[0]
                hashed_new_password = hash_password(new_password)

                with lock:
                    user_credentials[username] = hashed_new_password
                    # Save credentials immediately after successful registration
                    # save_credentials(user_credentials) # Moved save outside lock

                save_credentials(user_credentials) # Save the updated credentials

                print(color_text(f"{get_current_time()} [Auth] User '{username}' registered successfully from {addr}.", "green"))
                login_successful = True
                client_socket.send("Registration successful.\n".encode("utf-8")) # Send registration success first
                # Proceed to post-login actions below

            else:
                # Invalid registration format or mismatch
                client_socket.send("Invalid registration password format or passwords do not match.\n".encode("utf-8"))
                print(color_text(f"{get_current_time()} [Auth] Invalid registration attempt for '{username}' from {addr}.", "yellow"))
                return # Exit handle_login

        # --- Post-Login / Post-Registration Actions (only if login_successful is True) ---
        if login_successful:
            with lock:
                clients[client_socket] = username # Add to active clients list
            print(color_text(f"{get_current_time()} [Connect] {username} joined from {addr}.", "cyan"))

            welcome_msg = format_for_client(f"Welcome to {SERVER_NAME}, {username}!", "[Welcome]") + "\n"
            client_socket.send(welcome_msg.encode("utf-8"))

            with lock:
                is_op = username in ops
            if is_op:
                client_socket.send(format_for_client("You are logged in as an Operator.", "[Info]").encode("utf-8") + b"\n")

            join_msg = format_for_client(f"{username} has joined the chat!", "[Info]")
            broadcast(join_msg, client_socket) # Notify others

            # Start the dedicated handler thread for this client
            client_thread = threading.Thread(target=handle_client, args=(client_socket, username), name=f"Client-{username}")
            client_thread.daemon = True
            client_thread.start()

    except socket.timeout:
        print(color_text(f"{get_current_time()} [Auth] Login/Registration timeout from {addr}", "yellow"))
        try: client_socket.send("Timeout during login/registration. Connection closed.\n".encode("utf-8"))
        except: pass
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
        print(color_text(f"{get_current_time()} [Auth] Connection lost during login/registration from {addr}: {e}", "yellow"))
    except Exception as e:
        print(color_text(f"{get_current_time()} [Auth Error] Error during login/registration from {addr}: {e}", "red"))
        import traceback
        traceback.print_exc() # Print stack trace for debugging auth errors
        try: client_socket.send("An error occurred during login/registration. Connection closed.\n".encode("utf-8"))
        except: pass
    finally:
        # Ensure timeout is reset if it was set
        try: client_socket.settimeout(None)
        except: pass

        # Crucially, ensure the socket is closed if login/registration failed *before* the handler thread was started
        if not login_successful:
            try:
                print(color_text(f"{get_current_time()} [Auth Cleanup] Closing socket for failed login/registration from {addr}.", "blue"))
                client_socket.close()
            except: pass # Ignore errors closing already potentially closed socket

# --- Shutdown/Restart/Console (Mostly Unchanged) ---

def shutdown_server(exit_code=0):
    """Gracefully shuts down the server."""
    global server_socket, clients
    print(color_text(f"{get_current_time()} [Shutdown] Shutting down server...", "red"))

    # Grab client list and clear the global dict under lock
    with lock:
        client_sockets_to_close = list(clients.keys())
        clients.clear() # Prevent new messages during shutdown

    shutdown_message = format_for_client("Server is shutting down. Goodbye!", "[Warning]") + "\n"
    print(color_text(f"{get_current_time()} [Shutdown] Closing {len(client_sockets_to_close)} client socket(s)...", "yellow"))
    for client in client_sockets_to_close:
        try:
            # Use a short timeout for sending the shutdown message
            client.settimeout(0.5)
            client.send(shutdown_message.encode("utf-8"))
            client.settimeout(None) # Reset timeout
            client.shutdown(socket.SHUT_RDWR) # Signal shutdown
        except: pass # Ignore errors sending/shutting down (client might be gone)
        finally:
            try: client.close() # Ensure close is attempted
            except: pass

    # Close the main server socket
    local_server_socket = server_socket # Copy reference
    server_socket = None # Signal that the server socket is closing/closed
    if local_server_socket:
        try:
            print(color_text(f"{get_current_time()} [Shutdown] Closing server socket.", "red"))
            local_server_socket.close()
        except Exception as e:
            print(color_text(f"{get_current_time()} [Shutdown Error] Error closing server socket: {e}", "red"))

    # Save state AFTER closing sockets
    print(color_text(f"{get_current_time()} [Shutdown] Saving state...", "yellow"))
    save_credentials(user_credentials) # Uses its own lock
    save_ops(ops) # Uses its own lock

    print(color_text(f"{get_current_time()} [Shutdown] Exiting.", "red"))
    sys.exit(exit_code) # Use sys.exit for cleaner exit than os._exit

def restart_server():
    """Shuts down clients and restarts the server script."""
    global server_socket, clients
    print(color_text(f"{get_current_time()} [Restart] Restarting server...", "red"))

    # Similar shutdown sequence as shutdown_server
    with lock:
        client_sockets_to_close = list(clients.keys())
        clients.clear()

    restart_message = format_for_client("Server is restarting. Please reconnect shortly.", "[Warning]") + "\n"
    print(color_text(f"{get_current_time()} [Restart] Closing {len(client_sockets_to_close)} client socket(s)...", "yellow"))
    for client in client_sockets_to_close:
        try:
            client.settimeout(0.5)
            client.send(restart_message.encode("utf-8"))
            client.settimeout(None)
            client.shutdown(socket.SHUT_RDWR)
        except: pass
        finally:
            try: client.close()
            except: pass

    local_server_socket = server_socket
    server_socket = None
    if local_server_socket:
        try:
            print(color_text(f"{get_current_time()} [Restart] Closing server socket.", "red"))
            local_server_socket.close()
        except Exception as e:
            print(color_text(f"{get_current_time()} [Restart Error] Error closing server socket: {e}", "red"))

    print(color_text(f"{get_current_time()} [Restart] Saving state...", "yellow"))
    save_credentials(user_credentials)
    save_ops(ops)

    print(color_text(f"{get_current_time()} [Restart] Executing restart...", "red"))
    try:
        # This replaces the current process with a new instance
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(color_text(f"{get_current_time()} [Restart Error] Failed to execute restart: {e}", "red"))
        os._exit(1) # Force exit if exec fails

# --- Console Command Handling ---
def console_commands():
    """Handles commands entered directly into the server console."""
    global ops, user_credentials
    # Ensure initial messages are seen
    print(color_text("Server console ready. Type /help for commands.", "magenta"), flush=True)
    time.sleep(0.1) # Short delay helps ensure message appears after startup logs
    print(color_text("[Console Thread] Started successfully. Waiting for input...", "blue"), flush=True)

    while True:
        # Reset flags/variables at the start of each loop iteration
        broadcast_needed = False
        broadcast_msg_console = ""
        kick_success = False
        broadcast_msg_kick = ""
        op_needs_save = False # Reset op save flag
        target_socket_deop = None # Reset socket reference for deop notification
        target_socket_op = None # Reset socket reference for op notification

        try:
            # Prompt and read input
            command_input = input("> ").strip()

            if not command_input:
                continue # Skip empty input

            if not command_input.startswith('/'):
                print(color_text("Console commands must start with /", "red"), flush=True)
                continue

            parts = command_input.split(" ", 2) # Split for commands like kick/op/deop
            cmd = parts[0].lower()

            # --- Handle each command type ---

            if cmd == "/kick":
                with lock: # Lock needed for clients dict modification and lookup
                    if len(parts) < 2:
                        print(color_text("Usage: /kick <username> [reason]", "red"), flush=True)
                    else:
                        username_to_kick = parts[1]
                        reason = parts[2] if len(parts) > 2 else "Console Kick"
                        target_socket_kick = None
                        for sock, user in clients.items():
                            if user == username_to_kick:
                                target_socket_kick = sock
                                break

                        if target_socket_kick:
                            kick_message = format_for_client(f"You have been kicked by the Console. Reason: {reason}", "[Kick]") + "\n"
                            try:
                                target_socket_kick.sendall(kick_message.encode("utf-8"))
                                time.sleep(0.1) # Give message time to send
                                target_socket_kick.shutdown(socket.SHUT_RDWR)
                            except OSError as e:
                                print(color_text(f"[Kick Error] Couldn't send kick/shutdown socket for {username_to_kick}: {e}", "red"), flush=True)
                            finally:
                                # Remove under lock regardless of send error
                                clients.pop(target_socket_kick, None)
                                try: target_socket_kick.close()
                                except: pass
                            kick_success = True
                            broadcast_msg_kick = format_for_client(f"{username_to_kick} was kicked by the Console. Reason: {reason}", "[Info]")
                            print(color_text(f"[Kick] Kicked {username_to_kick} from console. Reason: {reason}", "red"), flush=True) # Console confirmation
                        else:
                            print(color_text(f"User '{username_to_kick}' not found or not online.", "red"), flush=True)
                            kick_success = False
                # Lock released

            elif cmd == "/op":
                if len(parts) < 2:
                    print(color_text("Usage: /op <username>", "red"), flush=True)
                else:
                    username_to_op = parts[1]
                    with lock: # Lock needed for ops list, user_credentials read, and clients lookup
                        if username_to_op not in user_credentials:
                            print(color_text(f"User '{username_to_op}' does not exist (must be registered).", "red"), flush=True)
                        elif username_to_op in ops:
                            print(color_text(f"{username_to_op} is already an operator.", "yellow"), flush=True)
                        else:
                            ops.append(username_to_op)
                            # Save is done outside lock after checks
                            print(color_text(f"{username_to_op} is now an operator.", "green"), flush=True) # Console confirmation
                            # Find socket for notification *while holding lock*
                            for sock, user in clients.items():
                                if user == username_to_op:
                                    target_socket_op = sock
                                    break
                            # Mark for saving outside lock
                            op_needs_save = True
                    # Lock released
                    # Actions outside lock
                    if op_needs_save:
                        save_ops(ops) # Save the modified list
                        if target_socket_op: # Check if socket was found
                            try:
                                notify_msg = format_for_client("You have been promoted to Operator by the Console.", "[Info]") + "\n"
                                target_socket_op.send(notify_msg.encode("utf-8"))
                            except Exception as e:
                                print(color_text(f"[Info] Could not notify {username_to_op} of OP status: {e}", "yellow"), flush=True)


            elif cmd == "/deop":
                 if len(parts) < 2:
                     print(color_text("Usage: /deop <username>", "red"), flush=True)
                 else:
                     username_to_deop = parts[1]
                     op_removed = False
                     with lock: # Lock for ops modification and client lookup
                         if username_to_deop not in ops:
                             print(color_text(f"{username_to_deop} is not an operator.", "red"), flush=True)
                         else:
                             try:
                                 ops.remove(username_to_deop) # Modify ops list under lock
                                 op_removed = True
                                 op_needs_save = True # Mark for saving outside lock
                                 print(color_text(f"{username_to_deop} is no longer an operator.", "yellow"), flush=True) # Console confirmation
                                 # Find socket for notification *while holding lock*
                                 for sock, user in clients.items():
                                     if user == username_to_deop:
                                         target_socket_deop = sock
                                         break
                             except ValueError:
                                 print(color_text(f"Error removing {username_to_deop} from ops list (not found during remove?).", "red"), flush=True)
                                 op_removed = False # Ensure flag is false on error
                                 op_needs_save = False
                     # --- Lock is released ---
                     # Perform actions that don't need the lock *after* releasing it
                     if op_needs_save:
                         save_ops(ops) # Save the modified list
                         if target_socket_deop: # Check if socket was found
                             try:
                                 notify_msg = format_for_client("Your Operator status has been removed by the Console.", "[Info]") + "\n"
                                 target_socket_deop.send(notify_msg.encode("utf-8"))
                             except Exception as e:
                                 print(color_text(f"[Info] Could not notify {username_to_deop} of DEOP status: {e}", "yellow"), flush=True)


            elif cmd == "/msg":
                # No lock needed here, just prepares broadcast message
                if len(command_input.split(" ", 1)) < 2: # Check if there is a message part
                    print(color_text("Usage: /msg <message>", "red"), flush=True)
                else:
                    message_text = command_input.split(" ", 1)[1] # Get the full message
                    broadcast_msg_console = format_for_client(message_text, "[Console]")
                    print(color_text(f"{get_current_time()} [Console MSG]: {message_text}", "green"), flush=True) # Log to console
                    broadcast_needed = True # Set flag to broadcast

            elif cmd == "/list":
                with lock: # Lock needed to read clients
                    if not clients:
                        print(color_text("No users connected.", "yellow"), flush=True)
                    else:
                        print(color_text(f"Connected Users ({len(clients)}):", "yellow"), flush=True)
                        user_list = sorted(list(clients.values()))
                        for user in user_list:
                            print(f" - {user}", flush=True)
                # Lock released

            elif cmd == "/listops":
                with lock: # Lock needed to read ops
                    op_list = sorted(ops)
                    op_str = ", ".join(op_list) if op_list else "No operators defined."
                print(color_text(f"Current Operators: {op_str}", "yellow"), flush=True)
                # Lock released

            elif cmd == "/stop":
                print(color_text("Initiating server shutdown from console...", "red"), flush=True)
                broadcast(format_for_client("Server is shutting down NOW! (Issued by Console)", "[Warning]"), None) # Notify clients
                # Use a timer to allow broadcast to likely send before shutdown proceeds
                threading.Timer(0.2, shutdown_server).start()
                break # Exit console loop

            elif cmd == "/restart":
                print(color_text("Initiating server restart from console...", "red"), flush=True)
                broadcast(format_for_client("Server is restarting NOW! (Issued by Console)", "[Warning]"), None) # Notify clients
                threading.Timer(0.2, restart_server).start()
                break # Exit console loop

            elif cmd == "/help":
                # --- UPDATED CONSOLE Help Text ---
                help_output = """
Server Console Commands:
  /list             List connected users
  /msg <message>    Send a message to all users as [Console]
  /kick <user> [rsn] Kick a user
  /op <username>    Make a user an operator
  /deop <username>  Remove operator status
  /listops          List current operators
  /stop             Stop the server gracefully
  /restart          Restart the server gracefully
  /help             Show this help message
"""
                print(help_output, flush=True)
                # --- End Console Help Update ---

            else: # Unknown command
                print(color_text(f"Unknown console command: {cmd}. Type /help for commands.", "red"), flush=True)

            # --- Perform broadcasts outside the main command logic ---
            if kick_success and broadcast_msg_kick:
                broadcast(broadcast_msg_kick, None)
            if broadcast_needed and broadcast_msg_console:
                broadcast(broadcast_msg_console, None) # Pass the formatted message


        except EOFError: # Handle Ctrl+D
            print(color_text("\nEOF detected, stopping server...", "red"), flush=True)
            shutdown_server()
            break # Exit loop
        except KeyboardInterrupt: # Handle Ctrl+C
            print(color_text("\nCtrl+C detected, stopping server...", "red"), flush=True)
            shutdown_server()
            break # Exit loop
        except Exception as e:
            print(color_text(f"{get_current_time()} [Console Error] An error occurred: {e}", "red"), flush=True)
            import traceback
            traceback.print_exc() # Print full traceback for debugging console errors

    print(color_text("[Console Thread] Exited.", "blue"), flush=True)


# --- Main Server Function ---
def server():
    global server_socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Allow address reuse quickly after server restart
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError as e:
        # This might fail on some systems/configurations, often not critical
        print(color_text(f"{get_current_time()} [Warning] Could not set SO_REUSEADDR: {e} (might be normal on some systems).", "yellow"))

    try:
        server_socket.bind((HOST, PORT))
    except OSError as e:
        print(color_text(f"[FATAL ERROR] Could not bind to {HOST}:{PORT} - {e}", "red"))
        print(color_text("Check if the port is already in use or if you have permissions.", "red"))
        sys.exit(1)

    server_socket.listen(5) # Listen for incoming connections (backlog of 5)
    print(color_text(f"{get_current_time()} [Start] Server '{SERVER_NAME}' started on {HOST}:{PORT}", "green"))
    print(color_text(f"{get_current_time()} [Start] Base file directory: {os.path.abspath(FILE_DIRECTORY)}", "green"))
    print(color_text(f"{get_current_time()} [Start] User registration enabled: {ALLOW_USER_AUTHENTICATION}", "green")) # Log registration status
    print(color_text(f"{get_current_time()} [Start] Loaded {len(user_credentials)} user(s) and {len(ops)} operator(s).", "green"))


    # Start the console command handler thread
    console_thread = threading.Thread(target=console_commands, name="ConsoleThread")
    console_thread.daemon = True # Allows main thread to exit even if console thread is blocking on input
    console_thread.start()

    accept_thread_running = True
    while accept_thread_running:
        try:
            # Accept new connections - this blocks until a connection arrives
            client_socket, addr = server_socket.accept()
            # Start a new thread to handle the login process for this client
            login_thread = threading.Thread(target=handle_login, args=(client_socket, addr), name=f"Login-{addr}")
            login_thread.daemon = True # Allow main program to exit even if login threads are running
            login_thread.start()
        except OSError as e:
            # Check if the error indicates the socket was closed (e.g., during shutdown)
            if server_socket is None:
                print(color_text(f"{get_current_time()} [Info] Server socket closed, stopping accept loop.", "yellow"))
            else:
                print(color_text(f"{get_current_time()} [Error] OSError accepting connection: {e}", "red"))
            accept_thread_running = False # Exit the loop if socket is closed or has error
        except Exception as e:
            print(color_text(f"{get_current_time()} [Error] Unexpected error accepting connection: {e}", "red"))
            accept_thread_running = False # Stop the loop on any unexpected accept error

    print(color_text(f"{get_current_time()} [Info] Main accept loop terminated.", "yellow"))
    # Ensure shutdown is called if loop exits unexpectedly
    if server_socket is not None: # Check if shutdown was already initiated
         shutdown_server()

if __name__ == "__main__":
    try:
        server()
    except KeyboardInterrupt:
        print(color_text("\nCtrl+C detected in main execution, initiating shutdown...", "red"))
        # Shutdown logic is handled when the server() accept loop breaks or errors out,
        # or by the console thread's KeyboardInterrupt handler.
        if server_socket is not None:
            shutdown_server()
    except Exception as e:
        print(color_text(f"\n[FATAL ERROR] Unhandled exception in main execution: {e}", "red"))
        import traceback
        traceback.print_exc()
        try:
            if server_socket is not None:
                 shutdown_server(1) # Attempt graceful shutdown with error code
        except:
             os._exit(1) # Force exit if shutdown fails catastrophically
