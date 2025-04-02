import socket
import customtkinter as ctk
from tkinter import messagebox, BOTH, LEFT, RIGHT, TOP, X, Y, END, DISABLED, NORMAL # Import specific tkinter constants
import datetime
import threading
import re
import sys
import os
import json
import playsound
import tkinterdnd2 # NEW - Import the module directly
import time # Import time module
import webbrowser # NEW - For opening links

# --- Configuration Files ---
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
# Create download directory if it doesn't exist
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)
    print(f"[Info] Created download directory: {DOWNLOAD_DIR}")

SOUND_FILE = "sound_option.json"
SESSION_FILE = "session.json" # For remembering login details

def load_sound_setting():
    """Loads the notification sound setting from the JSON file."""
    try:
        with open(SOUND_FILE, "r") as file:
            return json.load(file).get("notification_sound", True)
    except (FileNotFoundError, json.JSONDecodeError):
        return True # Default to enabled if file missing or invalid

def save_sound_setting(value):
    """Saves the notification sound setting to the JSON file."""
    with open(SOUND_FILE, "w") as file:
        json.dump({"notification_sound": value}, file)

NOTIFICATION_SOUND = load_sound_setting()

# --- Session Load/Save ---
def load_session():
    """Loads session data (IP, Port, Username, optional Passwords) from session.json."""
    try:
        with open(SESSION_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        print("[Info] No valid session file found or error reading it.")
        return None

def save_session(data):
    """Saves session data to session.json."""
    try:
        with open(SESSION_FILE, "w") as file:
            json.dump(data, file, indent=4)
        print(f"[Info] Session saved.") # Don't print passwords if saved
    except IOError as e:
        print(f"[Error] Could not save session file: {e}")

def clear_session():
    """Deletes the session file."""
    if os.path.exists(SESSION_FILE):
        try:
            os.remove(SESSION_FILE)
            print("[Info] Session file cleared.")
        except OSError as e:
            print(f"[Error] Could not clear session file: {e}")


# Set dark mode theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Global variables for socket connection
client_socket = None
username = None

# --- UI Element Globals ---
root = None
login_window = None
login_button = None
# Login Entries
ip_entry = None
port_entry = None
password_entry = None # Server password entry
username_entry = None
user_password_entry = None # User password entry
# Login Checkboxes
remember_session_checkbox = None
save_passwords_checkbox = None # <<< NEW Checkbox
# Chat Window Elements
chat_window = None
message_box = None
message_entry = None
send_button = None
# Sidebars
control_sidebar_frame = None
file_sidebar_frame = None
file_sidebar_scrollable = None
file_sidebar_user_label = None
# Control Buttons
mute_button = None


# --- File Drop Handling (Upload Only) ---
def handle_file_drop(event):
    """Handles files dropped onto the chat window for upload."""
    global client_socket, username, root
    if not client_socket:
        display_message("Not connected to server.\n", "error")
        return

    try:
        if not root: return
        # Use tk.splitlist for proper handling of paths with spaces, etc.
        file_paths = root.tk.splitlist(event.data)
        if not file_paths: return

        # Process only the first file if multiple are dropped
        # Strip potential curly braces added by some systems (like Windows)
        file_path = file_paths[0].strip('{}').strip()

        if os.path.exists(file_path) and os.path.isfile(file_path):
            # --- Send upload command ---
            # NOTE: This still sends the local path. The server needs to be
            #       designed to handle this command and then potentially request
            #       the actual file data separately if doing real uploads.
            #       The current implementation assumes the server acts based on the path.
            command = f"/upload \"{file_path}\"" # Enclose path in quotes
            display_message(f"Initiating upload request for: {os.path.basename(file_path)}\n", "client_command_output")
            try:
                client_socket.send(command.encode("utf-8"))
            except (BrokenPipeError, OSError) as e:
                handle_disconnection(f"Failed to send upload command: {e}")
                return
        elif not os.path.exists(file_path):
            display_message(f"Error: Dropped file path not found: {file_path}\n", "error")
        else: # Path exists but is not a file (e.g., directory)
            display_message(f"Error: Dropped path is not a file: {file_path}\n", "error")

        if len(file_paths) > 1:
            display_message("Note: Only the first dropped file is being processed.\n", "client_command_output")

    except Exception as e:
        display_message(f"Error processing dropped file: {e}\n", "error")
        print(f"[Debug] Raw drop data: {event.data}")


# --- Login Function (Unchanged) ---
def login():
    global client_socket, username, login_window, login_button
    global ip_entry, port_entry, password_entry, username_entry, user_password_entry
    global remember_session_checkbox, save_passwords_checkbox # Include new checkbox

    server_ip = ip_entry.get()
    server_port_str = port_entry.get()
    server_password_input = password_entry.get()
    username_input = username_entry.get()
    user_password_input = user_password_entry.get()

    if not server_port_str.isdigit():
        messagebox.showerror("Error", "Server Port must be a number.")
        return
    server_port = int(server_port_str)

    # Check all required fields are filled
    if not all([server_ip, server_port_str, server_password_input, username_input, user_password_input]):
        messagebox.showerror("Error", "Please fill in all fields.")
        return

    if login_button: login_button.configure(state="disabled", text="Logging in...")

    # Get checkbox states
    is_remember_checked = bool(remember_session_checkbox.get()) if remember_session_checkbox else False
    is_save_passwords_checked = bool(save_passwords_checkbox.get()) if save_passwords_checkbox else False # <<< NEW

    try:
        if client_socket:
            try: client_socket.close()
            except OSError: pass
            client_socket = None

        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(10)
        client_socket.connect((server_ip, server_port))

        # --- Login Sequence (Unchanged from previous working version) ---
        response = client_socket.recv(1024).decode("utf-8", errors="ignore")
        print(f"[Debug Login] R1: {response}")
        client_socket.send(server_password_input.encode("utf-8"))
        response = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()
        print(f"[Debug Login] R2: {response}")
        if response == "Incorrect server password": raise ValueError("Incorrect server password.")
        if "Enter username:" not in response: raise ValueError(f"Unexpected response after server pass:\n'{response}'")
        client_socket.send(username_input.encode("utf-8"))
        response = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()
        print(f"[Debug Login] R3: {response}")
        if response == "Username rejected or does not exist.": raise ValueError("Username rejected or does not exist.")
        elif response == "Username already logged in.": raise ValueError("Username already logged in.")
        if "Enter password:" not in response: raise ValueError(f"Unexpected response after username:\n'{response}'")
        client_socket.send(user_password_input.encode("utf-8"))
        response = client_socket.recv(1024).decode("utf-8", errors="ignore").strip()
        print(f"[Debug Login] R4: {response}")
        if response == "Incorrect password.": raise ValueError("Incorrect password.")
        elif response != "Login successful.": raise ValueError(f"Unexpected final response:\n'{response}'")
        # --- End Login Sequence ---

        client_socket.settimeout(None)
        username = username_input

        # --- Handle Session Saving ---
        if is_remember_checked: # Only save if the main "Remember" box is checked
            session_data = {
                "ip": server_ip,
                "port": server_port_str,
                "username": username_input
            }
            if is_save_passwords_checked: # <<< NEW: Also check the password save box
                session_data["server_password"] = server_password_input
                session_data["user_password"] = user_password_input
                print("[Info] Saving session including passwords (UNSAFE).")
            else:
                print("[Info] Saving session (IP, Port, User only).")

            save_session(session_data)
        else:
            clear_session() # Clear session if main box is unchecked

        if login_window: login_window.withdraw()
        open_chat_window()
        recv_thread = threading.Thread(target=receive_messages, name="ReceiveThread", daemon=True)
        recv_thread.start()

    except ValueError as e:
         messagebox.showerror("Login Failed", str(e))
         if client_socket: client_socket.close()
         client_socket = None
    except socket.timeout:
        messagebox.showerror("Connection Error", "Connection timed out.")
        if client_socket: client_socket.close()
        client_socket = None
    except ConnectionRefusedError:
        messagebox.showerror("Connection Error", "Connection refused by the server.")
        if client_socket: client_socket.close()
        client_socket = None
    except socket.gaierror:
         messagebox.showerror("Connection Error", "Server IP/Hostname invalid or not found.")
         if client_socket: client_socket.close()
         client_socket = None
    except Exception as e:
        messagebox.showerror("Connection Error", f"An unexpected error occurred: {e}")
        if client_socket: client_socket.close()
        client_socket = None
    finally:
        if login_button and login_button.winfo_exists():
            if not client_socket:
                 login_button.configure(state="normal", text="Login")


# --- Open Chat Window (Added "file_status" tag) ---
def open_chat_window():
    global chat_window, message_box, message_entry, send_button, mute_button
    global control_sidebar_frame, file_sidebar_frame, file_sidebar_scrollable, file_sidebar_user_label
    global root

    if chat_window and chat_window.winfo_exists():
        chat_window.deiconify()
        if message_entry and message_entry.winfo_exists(): message_entry.configure(state="normal")
        if send_button and send_button.winfo_exists(): send_button.configure(state="normal")
        if file_sidebar_scrollable and file_sidebar_scrollable.winfo_exists(): update_file_sidebar("No user selected", []) # Update sidebar on reopen
        update_mute_button_text()
        chat_window.lift()
        return

    chat_window = ctk.CTkToplevel(root)
    chat_window.title(f"JAPIRC GUI Client - {username}")
    chat_window.geometry("850x550")
    chat_window.protocol("WM_DELETE_WINDOW", on_chat_window_close)

    # Left Sidebar
    control_sidebar_frame = ctk.CTkFrame(chat_window, width=150)
    control_sidebar_frame.pack(side=LEFT, fill=Y, padx=(10, 5), pady=10)
    # Main Content
    main_frame = ctk.CTkFrame(chat_window)
    main_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=5, pady=10)
    # Right Sidebar (File List)
    file_sidebar_frame = ctk.CTkFrame(chat_window, width=180)
    file_sidebar_frame.pack(side=RIGHT, fill=Y, expand=False, padx=(5, 10), pady=10)

    # Populate Left Sidebar
    ctk.CTkLabel(control_sidebar_frame, text="Controls", font=("default_theme", 16, "bold")).pack(pady=(10, 15), fill=X)
    logout_button = ctk.CTkButton(control_sidebar_frame, text="Logout/Switch Server", command=logout_action)
    logout_button.pack(pady=5, padx=10, fill=X)
    mute_button_text = "Mute Notifications" if NOTIFICATION_SOUND else "Unmute Notifications"
    mute_button = ctk.CTkButton(control_sidebar_frame, text=mute_button_text, command=toggle_sound_button_action)
    mute_button.pack(pady=5, padx=10, fill=X)
    github_button = ctk.CTkButton(control_sidebar_frame, text="GitHub Project", command=open_github_link)
    github_button.pack(pady=5, padx=10, fill=X)
    close_app_button = ctk.CTkButton(control_sidebar_frame, text="Close Application", command=close_app_action, fg_color="firebrick")
    close_app_button.pack(pady=(15, 10), padx=10, side="bottom") # Use string "bottom"

    # Populate Main Frame
    message_box = ctk.CTkTextbox(main_frame, state="disabled", wrap="word", font=("Arial", 12))
    message_box.pack(padx=0, pady=(0, 5), fill=BOTH, expand=True)
    # Configure message tags
    message_box.tag_config("incoming", foreground="#00BFFF") # DodgerBlue
    message_box.tag_config("outgoing", foreground="#7B68EE") # MediumSlateBlue
    message_box.tag_config("error", foreground="#FF0000")    # Red
    message_box.tag_config("client_command_output", foreground="#2E8B57") # SeaGreen
    message_box.tag_config("file_status", foreground="#00FFFF") # Cyan <<< NEW TAG for file transfers

    entry_frame = ctk.CTkFrame(main_frame)
    entry_frame.pack(padx=0, pady=(5, 0), fill=X)
    message_entry = ctk.CTkEntry(entry_frame)
    message_entry.pack(pady=5, side=LEFT, fill=X, expand=True, padx=(0, 5))
    message_entry.bind("<Return>", lambda event: send_message())
    send_button = ctk.CTkButton(entry_frame, text="Send", command=send_message, width=80)
    send_button.pack(pady=5, side=RIGHT)

    # DND Setup (For Upload)
    message_box.drop_target_register(tkinterdnd2.DND_FILES)
    message_box.dnd_bind('<<Drop>>', handle_file_drop)
    drop_label = ctk.CTkLabel(main_frame, text="Drag & Drop Files onto Chat Area to Upload", text_color="gray", font=("Arial", 10))
    # Use ctk constant if available (depends on CustomTkinter version), else string
    try: drop_label.pack(side=ctk.BOTTOM, pady=(0,5))
    except AttributeError: drop_label.pack(side="bottom", pady=(0,5))


    # Populate Right Sidebar (File List Display)
    file_sidebar_user_label = ctk.CTkLabel(file_sidebar_frame, text="Files:", anchor="w", font=("default_theme", 14, "bold"))
    file_sidebar_user_label.pack(side=TOP, fill=X, padx=5, pady=(5, 2))
    file_sidebar_scrollable = ctk.CTkScrollableFrame(file_sidebar_frame, label_text="") # Removed label_text
    file_sidebar_scrollable.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=(2, 5))
    update_file_sidebar("No user selected", []) # Initialize sidebar

    # Finalize
    chat_window.lift()
    chat_window.focus_force()
    message_entry.focus_set()


# --- Action Functions (Unchanged) ---
def logout_action():
    print("[Info] Logout button clicked.")
    on_chat_window_close()

def update_mute_button_text():
    global mute_button, NOTIFICATION_SOUND
    if mute_button and mute_button.winfo_exists():
        mute_button_text = "Mute Notifications" if NOTIFICATION_SOUND else "Unmute Notifications"
        mute_button.configure(text=mute_button_text)

def toggle_sound_button_action():
    toggle_sound()
    update_mute_button_text()

def open_github_link():
    url = "https://github.com/Nakildias/JAPIRC/"
    print(f"[Info] Opening URL: {url}")
    try:
        webbrowser.open(url, new=2)
    except Exception as e:
        print(f"[Error] Could not open web browser: {e}")
        display_message(f"Could not open link: {url}\nError: {e}\n", "error")

def close_app_action():
    print("[Info] Close App button clicked.")
    if client_socket:
        print("[Info] Disconnecting before closing...")
        handle_disconnection("Application closed by user.")
        if root:
            # Give a brief moment for potential socket closing actions
            root.update_idletasks()
            time.sleep(0.1)
    else:
        print("[Info] Not connected, destroying windows.")
        # Explicitly destroy windows if they exist
        if chat_window and chat_window.winfo_exists(): chat_window.destroy()
        if login_window and login_window.winfo_exists(): login_window.destroy()

    if root:
        print("[Info] Quitting root Tkinter application.")
        root.quit()
        root.destroy() # Ensure root is destroyed

# --- Chat Window Close Handling (Unchanged) ---
def on_chat_window_close():
    global client_socket, chat_window, login_window
    if client_socket:
        try:
            print("[Info] Sending /exit command...")
            client_socket.send("/exit".encode("utf-8"))
            time.sleep(0.1) # Give a moment for the message to send
        except (OSError, BrokenPipeError) as e:
            print(f"[Info] Error sending /exit (socket likely closed): {e}")
        finally:
            # Ensure socket is closed and set to None regardless of send success
            try:
                print("[Info] Closing client socket...")
                client_socket.close()
            except OSError as e:
                print(f"[Info] Error closing socket (already closed?): {e}")
            client_socket = None # Crucial: set to None after closing attempts

    if chat_window:
        print("[Info] Destroying chat window...")
        chat_window.destroy()
        chat_window = None # Crucial: set to None after destroying

    # Show login window after closing chat window
    if login_window and login_window.winfo_exists():
         try:
             print("[Info] Showing login window...")
             login_window.deiconify()
             login_window.lift()
             # Reset login button state if needed (though handle_disconnection might also do this)
             if login_button and login_button.winfo_exists():
                 login_button.configure(state="normal", text="Login")
         except Exception as e:
             print(f"[Error] Could not show login window: {e}. Quitting.")
             if root: root.quit()
    else:
        print("[Info] Login window not found or destroyed, quitting application.")
        if root: root.quit()


# --- Send Message Function (Unchanged) ---
def send_message():
    global client_socket, message_entry, username
    if not message_entry: return
    message = message_entry.get()
    if not message: return

    if not client_socket:
        display_message("Not connected to server.\n", "error")
        # Optionally trigger disconnect handling if trying to send while disconnected
        handle_disconnection("Attempted to send while disconnected.")
        return

    current_time_str = datetime.datetime.now().strftime("%X")

    try:
        # --- Client-Side Commands ---
        if message.startswith("/exit"):
            on_chat_window_close() # Handle exit locally first
            # The /exit command might still be sent by on_chat_window_close()
            # Avoid sending it twice here.
        elif message.startswith("/help"):
            show_help()
            message_entry.delete(0, END)
        elif message.startswith("/toggle_sound"):
            toggle_sound_button_action()
            message_entry.delete(0, END)

        # --- Server Commands ---
        elif message.startswith("/upload"):
            parts = message.split(" ", 1)
            # Basic check if a path seems to follow
            if len(parts) == 2 and parts[1].strip():
                local_path = parts[1].strip().strip('"') # Remove potential quotes
                if os.path.exists(local_path) and os.path.isfile(local_path):
                    # Send command with path in quotes for server
                    command_to_send = f'/upload "{local_path}"'
                    display_message(f"Initiating upload request for: {os.path.basename(local_path)}\n", "client_command_output")
                    client_socket.send(command_to_send.encode("utf-8"))
                elif not os.path.exists(local_path):
                    display_message(f"Error: Local file not found for upload: {local_path}\n", "error")
                else: # Path exists but isn't a file
                    display_message(f"Error: Path is not a file: {local_path}\n", "error")
            else:
                display_message("Usage: /upload <full_path_to_local_file>\n", "error")
            message_entry.delete(0, END)

        elif message.startswith("/files"):
            parts = message.split(" ", 1)
            if len(parts) == 2 and parts[1].strip():
                target_user = parts[1].strip()
                client_socket.send(message.encode("utf-8")) # Send raw command
                display_message(f"Requesting file list for user: {target_user}\n", "client_command_output")
            else:
                display_message("Usage: /files <username>\n", "error")
            message_entry.delete(0, END)

        # `/download` command block REMOVED. It will be sent to the server like any other command.

        elif message.startswith("/delete"):
            parts = message.split(" ", 1) # Check if at least one arg exists
            if len(parts) >= 2 and parts[1].strip():
                client_socket.send(message.encode("utf-8")) # Send raw command to server
                display_message(f"Sending delete request: {message}\n", "client_command_output")
            else:
                display_message("Usage: /delete <filename> OR /delete <user> <filename> (Operator only)\n", "error")
            message_entry.delete(0, END)

        else:
            # Send regular message or other server command
            client_socket.send(message.encode("utf-8"))
            # Display outgoing non-command messages
            if not message.startswith("/"):
                display_message(f"{current_time_str} [{username}]: {message}\n", "outgoing")
            message_entry.delete(0, END) # Clear entry after sending any message/command

    except (BrokenPipeError, OSError, ConnectionResetError) as e:
        handle_disconnection(f"Error sending message: {e}")
    except Exception as e:
         display_message(f"An unexpected error occurred sending the message: {e}\n", "error")
         # Optionally clear the entry even on unexpected errors
         if message_entry and message_entry.winfo_exists(): message_entry.delete(0, END)


# --- Receive Messages (Improved file transfer messages) ---
def receive_messages():
    global client_socket, username
    while client_socket:
        try:
            message_bytes = client_socket.recv(4096)
            if not message_bytes:
                handle_disconnection("Connection closed by server.")
                break

            # Attempt to decode the entire chunk first
            try:
                message = message_bytes.decode("utf-8", errors="ignore")
            except UnicodeDecodeError:
                print("[Warning] Decoding error, likely receiving binary data. Checking for header.")
                # If decode fails, check if it *starts* like a file transfer header
                if message_bytes.startswith(b"FILE_TRANSFER:"):
                    # Manually find the end of the header line
                    try:
                        header_end_index = message_bytes.index(b'\n') # Assuming newline ends header
                        header_line = message_bytes[:header_end_index].decode("utf-8", errors="ignore")
                        remaining_data = message_bytes[header_end_index+1:] # The rest is file data
                        message = header_line # Process the header
                        print(f"[Debug] Parsed header: {header_line}")
                        is_file_transfer_chunk = True
                    except (ValueError, UnicodeDecodeError) as e:
                         print(f"[Error] Couldn't parse potential file transfer header: {e}")
                         continue # Skip this chunk if header parsing fails
                else:
                    print("[Warning] Received undecodable non-file-transfer data. Skipping.")
                    continue # Skip if it doesn't look like our file transfer
            else:
                # If decode succeeded, check for file transfer header normally
                is_file_transfer_chunk = message.startswith("FILE_TRANSFER:")
                remaining_data = None # No remaining binary data if initial decode worked

            if not message: continue

            # --- File Transfer Handling ---
            if is_file_transfer_chunk:
                try:
                    _, filename, file_size_str = message.strip().split(":")
                    file_size = int(file_size_str)
                except (ValueError, IndexError) as e:
                    display_message(f"Error: Received malformed file transfer header: {message.strip()}\n", "error")
                    print(f"[Error] Malformed header details: {e}")
                    continue # Skip this faulty transfer attempt

                # Use the new "file_status" tag and nicer message
                display_message(f"⬇️ Receiving file: {filename} ({file_size} bytes)...\n", "file_status")

                save_path = os.path.join(DOWNLOAD_DIR, os.path.basename(filename)) # Sanitize filename

                try:
                    with open(save_path, "wb") as file:
                        bytes_received = 0
                        # If we already have some data from the header chunk
                        if remaining_data:
                            file.write(remaining_data)
                            bytes_received += len(remaining_data)
                            print(f"[Debug File] Wrote initial {len(remaining_data)} bytes.")

                        while bytes_received < file_size:
                            # Adjust chunk size based on remaining bytes needed
                            bytes_to_recv = min(4096, file_size - bytes_received)
                            if bytes_to_recv <= 0: break # Should not happen, but safety check

                            chunk = client_socket.recv(bytes_to_recv)
                            if not chunk:
                                display_message(f"Warning: Connection closed unexpectedly during download of {filename}.\n", "error")
                                break # Exit inner loop
                            file.write(chunk)
                            bytes_received += len(chunk)
                            # Optional: Add progress update here if needed (complex)
                            # print(f"[Debug File] Received chunk: {len(chunk)} bytes. Total: {bytes_received}/{file_size}")

                    if bytes_received == file_size:
                         # Use the new "file_status" tag and nicer completion message
                         display_message(f"✅ File '{os.path.basename(filename)}' saved to Downloads folder.\n", "file_status")
                         play_notification_sound() # Play sound on successful download
                    else:
                         display_message(f"❌ Download incomplete for {filename}. Received {bytes_received}/{file_size} bytes.\n", "error")
                         # Optionally delete the incomplete file
                         # if os.path.exists(save_path): os.remove(save_path)

                except IOError as e:
                    display_message(f"Error saving file {filename}: {e}\n", "error")
                except Exception as e:
                    display_message(f"An unexpected error occurred during file download: {e}\n", "error")

                continue # Skip normal message handling for this packet

            # --- Regular Message Handling ---
            # Handle potentially multiple messages in one recv
            messages = [m for m in message.split('\n') if m] # Split and remove empty strings

            for msg_line in messages:
                msg_line = msg_line.strip()
                if not msg_line: continue

                print(f"[Debug Recv] {msg_line}") # Log raw message line

                if msg_line.startswith("FILE_LIST:"):
                    try:
                        parts = msg_line.strip().split(":", 2)
                        if len(parts) == 3:
                            list_user = parts[1]
                            filenames_str = parts[2]
                            # Split by semicolon and filter out potential empty strings
                            filenames = [fn for fn in filenames_str.split(';') if fn]
                            # Schedule UI update on main thread
                            if chat_window and chat_window.winfo_exists():
                                chat_window.after(0, update_file_sidebar, list_user, filenames)
                        else:
                             display_message(f"Received malformed FILE_LIST from server: {msg_line}\n", "error")
                    except Exception as e:
                         display_message(f"Error processing FILE_LIST: {e}\n", "error")

                # If not a special message handled above, display as regular incoming message
                else:
                    cleaned_message = process_ansi_colors(msg_line) # Remove potential server-side colors
                    display_message(f"{cleaned_message}\n", "incoming")

                    # Play sound logic (basic check)
                    # Avoid sound for own messages or simple status messages
                    is_own_message_approx = f"[{username}]:" in cleaned_message
                    # Heuristic for server status messages (might need refinement)
                    try:
                        is_server_status = cleaned_message.startswith(f"{datetime.datetime.now().strftime('%X')} [") and cleaned_message.strip().endswith("]")
                    except Exception: # Catch potential errors in strftime format etc.
                        is_server_status = False

                    if NOTIFICATION_SOUND and not is_own_message_approx and not is_server_status:
                        play_notification_sound()

        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"[Info] Connection error in receive loop: {e}")
            # Check if socket is already None (means disconnect handled elsewhere)
            if client_socket:
                handle_disconnection(f"Connection lost ({type(e).__name__}).")
            break # Exit loop
        except Exception as e:
            print(f"[Critical Error] Error receiving message: {e}")
            # Ensure stack trace is printed for unexpected errors
            import traceback
            traceback.print_exc()
            if client_socket: # Check if socket exists before handling disconnect
                handle_disconnection(f"An unexpected error occurred ({type(e).__name__}).")
            break # Exit loop

    print("[Info] Receive thread terminating.")


# --- NEW: Function to request file download ---
def request_file_download(filename, uploader):
    """Sends a /download command to the server for the specified file."""
    global client_socket
    if not client_socket:
        display_message("Cannot download: Not connected to server.\n", "error")
        return

    # Add quotes around filename in case it contains spaces
    command = f'/download {uploader} "{filename}"'
    display_message(f"Requesting download: {filename} from {uploader}\n", "client_command_output")

    try:
        client_socket.send(command.encode("utf-8"))
    except (BrokenPipeError, OSError) as e:
        handle_disconnection(f"Error sending download request: {e}")
    except Exception as e:
        display_message(f"An unexpected error occurred sending download request: {e}\n", "error")


# --- Update Sidebar (Added click binding) ---
def update_file_sidebar(list_username, filenames):
    """Updates the file list sidebar. Files are clickable to initiate download."""
    if not file_sidebar_scrollable or not file_sidebar_scrollable.winfo_exists():
        print("[Debug] Sidebar not ready for update.")
        return

    if file_sidebar_user_label and file_sidebar_user_label.winfo_exists():
        file_sidebar_user_label.configure(text=f"Files from {list_username}:")

    # Clear existing file labels
    for widget in file_sidebar_scrollable.winfo_children():
        widget.destroy()

    if not filenames:
        no_files_label = ctk.CTkLabel(file_sidebar_scrollable, text="No files found.", text_color="gray")
        no_files_label.pack(pady=5, anchor="w") # Use anchor='w' for left alignment
        return

    # Add new file labels (as clickable text)
    for filename in sorted(filenames): # Sort for consistency
        if not filename: continue # Skip empty names if server sends them
        file_label = ctk.CTkLabel(
            file_sidebar_scrollable,
            text=filename,
            cursor="hand2", # <<< ADDED cursor to indicate clickable
            anchor="w" # anchor='w' for left alignment
        )
        file_label.pack(fill=X, padx=5, pady=1) # fill=X makes text fill width
        # BINDING ADDED - Clicking the label calls request_file_download
        file_label.bind("<Button-1>", lambda event, fn=filename, uploader=list_username: request_file_download(fn, uploader))


# --- Play Sound (Unchanged) ---
def play_notification_sound():
    """Plays the notification sound in a separate thread if enabled."""
    def play_sound():
        sound_file = "notification.wav" # Ensure this file exists in the same directory
        try:
            if os.path.exists(sound_file):
                playsound.playsound(sound_file, block=False) # block=False prevents freezing
            else:
                # Only print warning if sound is supposed to be enabled
                if NOTIFICATION_SOUND:
                    print(f"[Sound] Notification sound file not found: {sound_file}")
        except Exception as e:
            # Catch playsound specific errors or other issues
            # Playsound might have platform-specific issues or dependencies.
            print(f"[Sound Error] Error playing sound: {e}")

    if NOTIFICATION_SOUND:
        # Run in a separate thread to avoid blocking UI or network operations
        threading.Thread(target=play_sound, name="SoundThread", daemon=True).start()

# --- Handle Disconnection (Unchanged) ---
def handle_disconnection(reason="Connection lost."):
    global client_socket, chat_window, message_entry, send_button, file_sidebar_scrollable, login_window, login_button

    print(f"[Info] Handling disconnection: {reason}")

    # Prevent multiple disconnect calls race conditions
    socket_to_close = client_socket
    if socket_to_close:
        client_socket = None # Set global to None immediately
        try:
            print("[Info] Closing socket due to disconnection.")
            socket_to_close.close()
        except OSError as e:
            print(f"[Info] Non-critical error closing socket on disconnect: {e}")

    # Schedule UI updates on the main thread
    def update_ui_on_disconnect():
        display_message(f"\n--- DISCONNECTED ---\n{reason}\n", "error")
        # Update file sidebar to show disconnected state
        if file_sidebar_scrollable and file_sidebar_scrollable.winfo_exists():
            update_file_sidebar("Disconnected", [])
        # Disable chat input if chat window still exists
        if chat_window and chat_window.winfo_exists():
            display_message("Please use the Login window to reconnect or close the application.\n", "client_command_output")
            if message_entry and message_entry.winfo_exists(): message_entry.configure(state="disabled")
            if send_button and send_button.winfo_exists(): send_button.configure(state="disabled")
        # Show and enable login window
        if login_window and login_window.winfo_exists():
            try:
                login_window.deiconify()
                login_window.lift()
                # Ensure login button is enabled
                if login_button and login_button.winfo_exists():
                    login_button.configure(state="normal", text="Login")
            except Exception as e: print(f"Error showing/enabling login window on disconnect: {e}")
        else: print("[Info] Login window not available during disconnect handling.")

    if root and root.winfo_exists():
        root.after(0, update_ui_on_disconnect)
    else:
        # If root is gone, can't schedule UI updates
        print("[Error] Root window doesn't exist, cannot schedule UI updates for disconnection.")

# --- Display Message (Unchanged) ---
def display_message(message, tag):
    """Safely displays a message in the message_box from any thread."""
    def _insert():
        global message_box
        if message_box and message_box.winfo_exists():
            try:
                message_box.configure(state="normal") # Enable writing
                message_box.insert(END, message, tag) # Insert text with tag
                message_box.configure(state="disabled") # Disable writing
                message_box.see(END) # Auto-scroll to the bottom
            except Exception as e:
                # Log error if insertion fails
                print(f"Error displaying message: {e}\nMessage: {message}")
        else:
            # Log if message_box is somehow not available (e.g., called after chat closed)
            print(f"[Debug] Message box not available for: {message}")

    # Schedule the insert operation on the main Tkinter thread
    if root:
        try:
            # Use after(0) to schedule the call as soon as possible in the event loop
            root.after(0, _insert)
        except Exception as e: # Catch potential errors if root is destroyed during scheduling
            print(f"Error scheduling message display on root: {e}")
    else:
        # Log if root isn't available for scheduling
        print(f"[Error] Cannot schedule display for message (UI root not ready?): {message}")

# --- Process ANSI (Unchanged) ---
def process_ansi_colors(message):
    """Removes ANSI escape codes from a string."""
    ansi_pattern = r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
    return re.sub(ansi_pattern, '', message)

# --- Show Help Function (Updated sidebar description) ---
def show_help():
    """Displays available client and server commands in the chat box."""
    help_message = (
        "--- Client Commands ---\n"
        " /help             - Shows this help message\n"
        " /exit             - Disconnects and shows login window\n"
        " /toggle_sound     - Toggle notification sound on/off\n"
        "--- Server Commands (Sent to Server) ---\n"
        " /files <user>     - Lists files uploaded by <user> (updates sidebar)\n"
        " /download <user> <filename> - Request download of a file from <user>\n"
        " /upload <path>    - (Or Drag & Drop) Request upload of local file\n"
        " /delete <filename>- Request deletion of your own uploaded file\n"
        " /list             - List connected users online\n"
        "--- Operator Only Commands ---\n"
        " /delete <user> <fn> - Request deletion of a specific user's file\n"
        " /kick <user> [reason] - Kick a user from the server\n"
        " /op <username>      - Make a user an operator\n"
        " /deop <username>    - Remove operator status\n"
        " /listops          - List server operators\n"
        " /stop /restart    - Stop or restart the server (Use with caution!)\n"
        "-----------------------\n"
        " Drag & Drop a file onto the chat area to request upload.\n"
        " Click a filename in the right sidebar (after /files) to request download.\n" # <<< Updated sidebar role
    )
    display_message(help_message, "client_command_output")

# --- Toggle Sound (Unchanged) ---
def toggle_sound():
    """Toggles the notification sound on or off and saves the setting."""
    global NOTIFICATION_SOUND
    NOTIFICATION_SOUND = not NOTIFICATION_SOUND
    save_sound_setting(NOTIFICATION_SOUND)
    status = "enabled" if NOTIFICATION_SOUND else "disabled"
    display_message(f" Notification sound {status}.\n", "client_command_output")


# --- Main Application Setup (Unchanged) ---
def main():
    global root, login_window, ip_entry, port_entry, password_entry, username_entry, user_password_entry, login_button
    global remember_session_checkbox, save_passwords_checkbox # <<< Make new checkbox global

    # Use tkinterdnd2 Tk object as the root
    # This provides the necessary DND functionality for the application
    root = tkinterdnd2.Tk()
    root.withdraw() # Hide the main root window, we use Toplevels

    # --- Load Session Data ---
    loaded_session = load_session()

    # --- Create Login Window ---
    login_window = ctk.CTkToplevel(root)
    login_window.title("JAPIRC GUI Login")
    login_window.geometry("350x550")

    def on_login_window_close():
        if not chat_window or not chat_window.winfo_exists():
            print("[Info] Login window closed and no chat window active. Quitting.")
            if root: root.quit()
        else:
            # If chat window exists, just hide the login window
            print("[Info] Login window closed, but chat window active. Hiding login.")
            login_window.withdraw()
    login_window.protocol("WM_DELETE_WINDOW", on_login_window_close)

    # --- Login Widgets ---
    ctk.CTkLabel(login_window, text="Server IP").pack(pady=(20, 2))
    ip_entry = ctk.CTkEntry(login_window, width=250, placeholder_text="e.g., 127.0.0.1 or example.com")
    ip_entry.pack(pady=1)

    ctk.CTkLabel(login_window, text="Server Port").pack(pady=(10, 2))
    port_entry = ctk.CTkEntry(login_window, width=250, placeholder_text="e.g., 6667")
    port_entry.pack(pady=1)

    ctk.CTkLabel(login_window, text="Server Password").pack(pady=(10, 2))
    password_entry = ctk.CTkEntry(login_window, show="*", width=250)
    password_entry.pack(pady=1)

    ctk.CTkLabel(login_window, text="Username").pack(pady=(10, 2))
    username_entry = ctk.CTkEntry(login_window, width=250, placeholder_text="Alphanumeric, no spaces")
    username_entry.pack(pady=1)

    ctk.CTkLabel(login_window, text="User Password").pack(pady=(10, 2))
    user_password_entry = ctk.CTkEntry(login_window, show="*", width=250)
    user_password_entry.pack(pady=1)

    # --- Remember Session Checkbox (IP/Port/User) ---
    remember_session_checkbox = ctk.CTkCheckBox(login_window, text="Remember Connection Info (IP, Port, User)")
    remember_session_checkbox.pack(pady=(15, 5)) # Add some bottom padding

    # --- NEW: Save Passwords Checkbox & Warning ---
    save_passwords_checkbox = ctk.CTkCheckBox(login_window, text="Save Passwords with Connection Info")
    save_passwords_checkbox.pack(pady=(0, 5)) # Place below the first checkbox

    warning_label = ctk.CTkLabel(login_window, text="Warning: Saving passwords is NOT secure!", text_color="orange", font=("default_theme", 10))
    warning_label.pack(pady=(0, 10))
    # --- End New Checkbox/Warning ---


    # --- Pre-fill from Session ---
    if loaded_session:
        print("[Info] Pre-filling login info from session file.")
        ip_entry.insert(0, loaded_session.get("ip", ""))
        port_entry.insert(0, loaded_session.get("port", ""))
        username_entry.insert(0, loaded_session.get("username", ""))
        # Check the main remember box if session was loaded
        remember_session_checkbox.select()

        # --- NEW: Pre-fill Passwords and check password box ---
        server_pass = loaded_session.get("server_password")
        user_pass = loaded_session.get("user_password")
        if server_pass:
            password_entry.insert(0, server_pass)
        if user_pass:
            user_password_entry.insert(0, user_pass)

        # Check the save passwords box ONLY if passwords were found in the session
        if server_pass or user_pass:
            save_passwords_checkbox.select()
        else:
            save_passwords_checkbox.deselect()
        # --- End Password Pre-fill ---

        # Focus password field if username was loaded, otherwise IP
        if loaded_session.get("username"):
             # Focus server password first if user known
             password_entry.focus_set()
        else:
             ip_entry.focus_set() # Default focus if only IP/port loaded
    else:
        # Default focus and checkbox state if no session loaded
        ip_entry.focus_set()
        remember_session_checkbox.deselect()
        save_passwords_checkbox.deselect() # <<< Ensure new box is also off


    # --- Login Button ---
    login_button = ctk.CTkButton(login_window, text="Login", command=login, width=100)
    login_button.pack(pady=15) # Adjusted padding

    # --- Start Main Loop ---
    print("[Info] Starting Tkinter main loop...")
    # Use root.mainloop() which is now the tkinterdnd2.Tk() instance
    root.mainloop()
    print("[Info] Tkinter main loop finished.")

if __name__ == "__main__":
    # Ensure the script uses UTF-8 for file paths, especially on Windows
    if sys.platform == "win32":
        try:
            # This helps with console output encoding on Windows sometimes
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            # Might not be available on older Python versions or specific setups
            print("[Warning] Could not reconfigure stdout/stderr encoding.")
            pass

    main()
