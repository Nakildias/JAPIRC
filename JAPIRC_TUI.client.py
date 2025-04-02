import curses
import curses.textpad
import datetime
import json
import os
import re
import signal
import socket
import sys
import threading
import time
import atexit # Import atexit

try:
    # Optional sound dependency
    from playsound import playsound
    SOUND_ENABLED = True
except ImportError:
    SOUND_ENABLED = False

# --- Configuration Constants ---
MAX_LENGHT = 512
CONNECT_TIMEOUT = 10
INPUT_TIMEOUT = 100 # Milliseconds for non-blocking input check
SETTINGS_DIR = os.path.expanduser("./") # Changed to current directory for simplicity
SOUND_FILE = os.path.join(SETTINGS_DIR, "sound_option.json")
SESSION_FILE = os.path.join(SETTINGS_DIR, "session.json")
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
NOTIFICATION_SOUND_FILE = 'notification.wav' # Assumed to be in the same dir as the script or configured path

# --- Global State ---
CURRENT_USER = ""
NOTIFICATION_SOUND_ACTIVE = True
client_socket = None
messages = []
message_lock = threading.Lock()
needs_redraw = threading.Event()
_intentional_exit = False # Flag for intentional exit (e.g., /exit, Ctrl+C)
_exiting_gracefully = False # Flag to prevent double exit attempts from signal handler
waiting_for_reconnect_ack = False # NEW: Flag when waiting for user reconnect confirmation

# --- Utility Functions ---

def ensure_settings_dir():
    """Creates the settings directory if it doesn't exist."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)

def load_sound_setting():
    """Loads the sound notification setting from a JSON file."""
    global NOTIFICATION_SOUND_ACTIVE
    ensure_settings_dir()
    if not SOUND_ENABLED:
        NOTIFICATION_SOUND_ACTIVE = False
        return False
    try:
        with open(SOUND_FILE, "r") as file:
            settings = json.load(file)
            enabled = settings.get("notification_sound", True)
            NOTIFICATION_SOUND_ACTIVE = bool(enabled)
            return NOTIFICATION_SOUND_ACTIVE
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        NOTIFICATION_SOUND_ACTIVE = True # Default to True if file missing/invalid
        return True

def save_sound_setting(is_enabled):
    """Saves the sound notification setting to a JSON file."""
    ensure_settings_dir()
    if not SOUND_ENABLED: return
    try:
        with open(SOUND_FILE, "w") as file:
            json.dump({"notification_sound": bool(is_enabled)}, file)
    except IOError:
        pass # Ignore errors saving settings

def load_session():
    """Loads session data including user password from a JSON file."""
    ensure_settings_dir()
    try:
        with open(SESSION_FILE, "r") as file:
            data = json.load(file)
            # Check for all expected keys, including user_password
            required_keys = ("server_ip", "server_port", "server_password", "username", "user_password")
            if all(k in data for k in required_keys):
                data["server_port"] = int(data["server_port"])
                return data
            else: # Handle older session files possibly missing user_password
                if all(k in data for k in ("server_ip", "server_port", "server_password", "username")):
                    data["server_port"] = int(data["server_port"])
                    data["user_password"] = None # Indicate missing password explicitly
                    return data
                else:
                    return {} # Missing other crucial keys
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return {} # Return empty dict on any error

# ### SECURITY WARNING ###
# Storing passwords (server or user) in plain text is HIGHLY INSECURE.
# Use this feature with extreme caution and only on trusted systems. Consider
# using OS keyring integration or other secure storage mechanisms in a real application.
def save_session(ip, port, server_password, username, user_password):
    """Saves session data including user password to a JSON file."""
    ensure_settings_dir()
    session_data = {
        "server_ip": ip,
        "server_port": port,
        "server_password": server_password, # <<< SECURITY RISK >>>
        "username": username,
        "user_password": user_password      # <<< !!! EXTREME SECURITY RISK !!! >>>
    }
    try:
        with open(SESSION_FILE, "w") as file:
            json.dump(session_data, file, indent=4)
    except IOError:
        pass # Ignore errors saving session

def strip_ansi_codes(text):
    """Removes ANSI escape sequences (like colors) from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def play_notification_sound():
    """Plays the notification sound in a separate thread if enabled and available."""
    if NOTIFICATION_SOUND_ACTIVE and SOUND_ENABLED and os.path.exists(NOTIFICATION_SOUND_FILE):
        try:
            # Run playsound in a separate thread to avoid blocking the UI
            threading.Thread(target=playsound, args=(NOTIFICATION_SOUND_FILE,), daemon=True).start()
        except Exception:
            pass # Ignore playsound errors silently

def add_message(text, color_pair_index_or_attr, play_sound=True):
    """
    Safely adds a message to the message list and signals UI redraw.
    Accepts either a color pair index (int) or a combined attribute (int).
    Removes null characters before adding.
    """
    global messages

    # Sanitize the text to remove/replace null bytes which crash curses
    if isinstance(text, str): # Ensure it's a string first
        if '\x00' in text:
            # Replace null bytes with a placeholder '?'
            text = text.replace('\x00', '?')
            # Optionally log this:
            # print(f"DEBUG: Replaced null byte in message: {repr(text)}", file=sys.stderr)

    with message_lock:
        # Store the text and its associated attribute (can be color pair index or combined)
        messages.append((text, color_pair_index_or_attr))
    needs_redraw.set() # Signal the main loop that the UI needs to be updated
    if play_sound: # Only play sound if requested (and enabled)
        play_notification_sound()


# --- Curses UI Functions ---

def init_colors():
    """Initializes color pairs for the curses UI."""
    curses.start_color()
    curses.use_default_colors() # Use terminal's default background
    # Define color pairs (foreground, background). -1 means default background.
    curses.init_pair(1, curses.COLOR_MAGENTA, -1) # User's own messages (Maybe Bold)
    curses.init_pair(2, curses.COLOR_CYAN, -1)     # Incoming server/user messages
    curses.init_pair(3, curses.COLOR_RED, -1)      # Errors
    curses.init_pair(4, curses.COLOR_GREEN, -1)    # Info, Help, File Lists (Maybe Bold for headers)
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE) # Status Bar
    curses.init_pair(6, curses.COLOR_YELLOW, -1)   # Input prompt, Status messages (Maybe Bold)
    curses.init_pair(7, curses.COLOR_WHITE, -1)    # Reconnect prompt color

def create_windows(max_y, max_x):
    """Creates the chat, input, and status windows based on terminal size."""
    if max_y < 5 or max_x < 10:
        raise curses.error("Terminal too small (minimum 5 rows, 10 columns required)")
    status_h = 1
    input_h = 3 # Height for border + 1 line of input
    chat_h = max_y - status_h - input_h
    # Create windows: height, width, begin_y, begin_x
    chat_win = curses.newwin(chat_h, max_x, 0, 0)
    chat_win.scrollok(True) # Allow window content to scroll
    input_win = curses.newwin(input_h, max_x, chat_h, 0)
    input_win.keypad(True) # Enable reading special keys like PgUp/PgDn
    status_win = curses.newwin(status_h, max_x, max_y - status_h, 0)
    return chat_win, input_win, status_win

def redraw_chat(win, scroll_pos):
    """Redraws the chat window with messages, handling scrolling and word wrap."""
    win.erase()
    win.border()
    max_y, max_x = win.getmaxyx()
    inner_h, inner_w = max_y - 2, max_x - 2 # Available space inside border
    if inner_h <= 0 or inner_w <= 0: return # Cannot draw if too small

    with message_lock:
        # Calculate which messages to display based on scroll position
        end_index = len(messages) - scroll_pos
        start_index = max(0, end_index - inner_h) # Show the last 'inner_h' messages
        display_msgs = messages[start_index:end_index]
        line_num = 1 # Start drawing from the first line inside the border

        for msg_text, attr_or_color_idx in display_msgs:
            # Determine the attribute to use. If it's just an index, get the color pair.
            # If it already includes attributes (like A_BOLD), use it directly.
            if isinstance(attr_or_color_idx, int) and attr_or_color_idx < 256: # Heuristic: likely a color index
                attr = curses.color_pair(attr_or_color_idx)
                # Apply default bolding based on color index if needed (example)
                if attr_or_color_idx == 1: attr |= curses.A_BOLD # User's own messages bold
                # elif attr_or_color_idx == 4: attr |= curses.A_BOLD # Example: Make info bold
            else: # It's likely already a combined attribute (e.g., curses.color_pair(4) | curses.A_BOLD)
                attr = attr_or_color_idx

            # Simple word wrapping (split message into lines that fit inner_w)
            start = 0
            while start < len(msg_text):
                if line_num > inner_h: break # Stop if window is full
                segment = msg_text[start : start + inner_w]
                try:
                    # Add the text segment to the window at the current line
                    win.addstr(line_num, 1, segment, attr)
                except curses.error:
                    # Ignore error if text doesn't fit exactly at line end (can happen)
                    pass
                line_num += 1
                start += inner_w # Move to the next segment start
            if line_num > inner_h: break # Stop outer loop if window full

    win.refresh() # Update the physical screen

def redraw_input(win, current_input_text):
    """Redraws the input window with the prompt and current user input OR the reconnect prompt."""
    global waiting_for_reconnect_ack
    win.erase()
    win.border()
    max_y, max_x = win.getmaxyx()
    inner_y, inner_x = 1, 1 # Position inside border

    # --- NEW: Check if waiting for reconnect confirmation ---
    if waiting_for_reconnect_ack:
        prompt_text = "Reconnect? (y/n) "
        prompt_len = len(prompt_text)
        prompt_attr = curses.color_pair(7) | curses.A_BOLD # White, Bold

        try:
            # Display the reconnect prompt
            win.addstr(inner_y, inner_x, prompt_text, prompt_attr)
            # Position cursor after the prompt
            win.move(inner_y, inner_x + prompt_len)
        except curses.error:
            pass # Ignore drawing errors
    else:
        # --- Original input drawing logic ---
        prompt = "[>] "
        prompt_len = len(prompt)
        input_width = max_x - 2 - prompt_len # Available width for typing
        if input_width <= 0: return # Cannot draw input area if too narrow

        text_to_display = current_input_text or ""
        # Calculate start position to show the end of the text if it's too long
        start_pos = max(0, len(text_to_display) - input_width)
        display_text = text_to_display[start_pos:]

        try:
            # Draw prompt (Yellow, Bold)
            win.addstr(inner_y, inner_x, prompt, curses.color_pair(6) | curses.A_BOLD)
            # Draw user input text (Default terminal color)
            win.addstr(inner_y, inner_x + prompt_len, display_text)
            # Move cursor to the end of the input text visually
            win.move(inner_y, inner_x + prompt_len + len(display_text))
        except curses.error:
            pass # Ignore drawing errors if terminal is squeezing

    win.refresh()


def redraw_status(win):
    """Redraws the status bar at the bottom."""
    global NOTIFICATION_SOUND_ACTIVE, CURRENT_USER
    win.erase()
    max_y, max_x = win.getmaxyx()
    sound_state = "ON" if NOTIFICATION_SOUND_ACTIVE else "OFF"
    if not SOUND_ENABLED: sound_state = "N/A"

    left_text = f" User: {CURRENT_USER or '???'}"
    # Updated status bar text
    right_text = f"Sound: {sound_state} | /help | PgUp/PgDn Scroll | Ctrl+C Exit "

    # Ensure text doesn't exceed window width
    status_text = f"{left_text}{right_text.rjust(max_x - len(left_text))}"[:max_x]

    try:
        status_attr = curses.color_pair(5) # White on Blue background pair
        # Apply background color to the whole line and add text
        win.bkgd(' ', status_attr)
        win.addstr(0, 0, status_text, status_attr)
    except curses.error:
        pass # Ignore drawing errors

    win.refresh()

def resize_ui(stdscr, chat_win, input_win, status_win):
    """Handles terminal resize events by recreating windows."""
    max_y, max_x = stdscr.getmaxyx()
    stdscr.clear() # Clear the main screen
    stdscr.refresh() # Refresh to apply clear

    try:
        # Recreate windows with new dimensions
        new_chat, new_input, new_status = create_windows(max_y, max_x)
        needs_redraw.set() # Signal a full redraw is needed with new windows
        return new_chat, new_input, new_status
    except curses.error:
        # Handle case where terminal is still too small after resize attempt
        try: # Attempt to display error message on the standard screen
            stdscr.addstr(0, 0, "Terminal too small. Please resize.", curses.A_REVERSE)
            stdscr.refresh()
            time.sleep(1) # Give user time to see message
        except curses.error:
            pass # Can't even display the error message if it's *really* small
        return None, None, None # Indicate failure to resize


# --- Network and Logic Functions ---

def handle_received_file(sock, filename, file_size):
    """Handles receiving a file chunk by chunk directly from the socket."""
    save_path = None # Define outside try block for cleanup
    try:
        filename = os.path.basename(filename) # Basic security: prevent directory traversal
        # Use Green (4) for download messages, no sound initially
        add_message(f"⬇️ Receiving file: {filename} ({file_size} bytes)...", 4, play_sound=False)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True) # Ensure download directory exists
        save_path = os.path.join(DOWNLOAD_DIR, filename)

        # Check for existing file and notify (Red=3, no sound)
        if os.path.exists(save_path):
            add_message(f"⚠️ Overwriting existing file: {filename}", 3, play_sound=False)

        bytes_received = 0
        with open(save_path, "wb") as f:
            while bytes_received < file_size:
                # Calculate chunk size, request up to 4096 bytes
                chunk_size = min(4096, file_size - bytes_received)
                if chunk_size <= 0: break # Should not happen if file_size is correct

                # *** CRITICAL: This recv() is now happening in the receiver thread context ***
                chunk = sock.recv(chunk_size)

                if not chunk:
                    # Handle unexpected connection close during transfer
                    raise ConnectionError("Connection lost during file transfer.")

                f.write(chunk)
                bytes_received += len(chunk)
                # Optional: Add a progress indicator message here if desired
                # e.g., add_message(f"Downloading {filename}: {bytes_received}/{file_size} bytes", 4, play_sound=False)
                # Be careful not to flood the message queue with progress updates.

        # Add final success message only if all bytes were received
        if bytes_received == file_size:
            # Success message (Green=4, default sound plays here if enabled)
            add_message(f"✅ File '{filename}' saved to {DOWNLOAD_DIR}", 4) # Default play_sound=True
        else:
            # This case means the loop exited before receiving all bytes
            raise ConnectionError(f"Incomplete file transfer. Expected {file_size}, got {bytes_received}.")

    except Exception as e:
        # Error message (Red=3, no sound)
        add_message(f"❌ File download failed for {filename}: {e}", 3, play_sound=False)
        # Attempt to remove potentially corrupted partial file
        try:
            if save_path and os.path.exists(save_path):
                os.remove(save_path)
                add_message(f"🧹 Cleaned up partial file: {filename}", 6, play_sound=False) # Yellow status
        except OSError as rm_err:
            add_message(f"⚠️ Could not remove partial file {filename}: {rm_err}", 3, play_sound=False)


# --- MODIFIED receive_messages_thread (for /files formatting) ---
def receive_messages_thread(sock):
    """Thread target function to continuously receive messages or handle file transfers."""
    global _intentional_exit
    while True:
        try:
            # Read data from the socket.
            message_bytes = sock.recv(2048) # Adjust buffer size if needed
            if not message_bytes:
                # Server closed the connection
                if not _intentional_exit:
                    add_message("Connection closed by server.", 3, play_sound=False)
                break # Exit the receiving thread

            # --- Decode potential first line for checks ---
            lines_bytes = message_bytes.split(b'\n', 1)
            potential_header_line_bytes = lines_bytes[0].strip()
            remaining_bytes = lines_bytes[1] if len(lines_bytes) > 1 else b""

            # --- Check for File Transfer FIRST ---
            is_file_transfer = False
            filename = ""
            file_size = 0
            if potential_header_line_bytes.startswith(b"FILE_TRANSFER:"):
                try:
                    header_str = potential_header_line_bytes.decode('utf-8', errors='replace')
                    _, filename, file_size_str = header_str.split(":", 2)
                    file_size = int(file_size_str)
                    is_file_transfer = True
                except (UnicodeDecodeError, ValueError, IndexError):
                    is_file_transfer = False # Invalid header

            if is_file_transfer:
                try:
                    # Call handle_received_file directly
                    handle_received_file(sock, filename, file_size)
                    # Note: Any data received *with* the header (remaining_bytes) is currently discarded.
                    # A more robust protocol/handler would buffer this.
                    continue # Go back to the start of the loop
                except Exception as file_e:
                    add_message(f"Error during file transfer processing: {file_e}", 3, play_sound=False)
                    continue

            # --- Check for File List (If Not File Transfer) ---
            is_file_list = False
            if potential_header_line_bytes.startswith(b"FILE_LIST:"):
                is_file_list = True

            if is_file_list:
                try:
                    # Decode the first line (header)
                    header_line = potential_header_line_bytes.decode("utf-8", errors='replace')
                    parts = header_line.strip().split(":", 2) # FILE_LIST : username : payload

                    if len(parts) == 3:
                        _list_command, username, payload = parts
                        username = username.strip()
                        payload = payload.strip()

                        # Format and add the header (Green, Bold)
                        header = f"----Files of {username}----"
                        header_attr = curses.color_pair(4) | curses.A_BOLD
                        add_message(header, header_attr, play_sound=False)

                        # Process payload from the header line (split by semicolon)
                        if payload:
                            filenames_on_header = payload.split(';')
                            for fname in filenames_on_header:
                                fname = fname.strip()
                                if fname:
                                    # Add indented filename (Green, Normal weight)
                                    add_message(f" {fname}", 4, play_sound=False)

                        # Process any remaining data received in the same chunk (split by newline, then semicolon)
                        if remaining_bytes:
                            remaining_text = remaining_bytes.decode("utf-8", errors='replace')
                            extra_lines = remaining_text.splitlines()
                            for line in extra_lines:
                                line = line.strip()
                                if line:
                                    filenames_on_line = line.split(';')
                                    for fname in filenames_on_line:
                                        fname = fname.strip()
                                        if fname:
                                            # Add indented filename (Green, Normal weight)
                                            add_message(f" {fname}", 4, play_sound=False)

                        # Format and add the footer (Green, Bold)
                        footer = "-" * len(header) # Match header length
                        footer_attr = curses.color_pair(4) | curses.A_BOLD
                        add_message(footer, footer_attr, play_sound=False)

                        needs_redraw.set() # Ensure UI updates
                        continue # Handled, skip default message handling for this block
                    else:
                        # Invalid FILE_LIST format, fall through to default handling below
                        add_message(f"Received malformed FILE_LIST header: {header_line}", 3, play_sound=False)

                except Exception as e:
                    add_message(f"Error processing FILE_LIST message: {e}", 3, play_sound=False)
                    # Fall through to default handling for the original bytes

            # --- Default Message Handling (If Not File Transfer or File List) ---
            # Decode the entire received data (or what's left after potential header processing)
            message = message_bytes.decode("utf-8", errors='replace') # Replace undecodable bytes
            message = strip_ansi_codes(message) # Remove any server-side color codes
            lines = message.splitlines()
            play_sound_for_message = len(lines) <= 1 # Only play sound for single-line messages

            for line in lines:
                if line: # Add non-empty lines
                    # Use cyan (color 2) for standard incoming messages
                    add_message(line, 2, play_sound=play_sound_for_message)
                    play_sound_for_message = False # Only play for the first line of a multi-line block

        # --- Exception Handling for the Loop ---
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as net_err:
            if not _intentional_exit:
                add_message(f"Connection lost: {net_err}", 3, play_sound=False)
            break # Exit thread
        except OSError as os_err:
            # Other socket errors (e.g., socket closed by main thread)
            if client_socket is None or _intentional_exit: # Socket closed gracefully or intentionally
                break
            else: # Unexpected OS error on the socket
                add_message(f"Network OS error: {os_err}", 3, play_sound=False)
                break
        except Exception as e:
            if not _intentional_exit:
                add_message(f"Error receiving/processing data: {repr(e)}", 3, play_sound=False)
                # import traceback; traceback.print_exc() # Uncomment for debugging
            break # Exit thread on unexpected errors

# --- End of receive_messages_thread ---


def show_client_help():
    """Adds the client and server command help text to the chat display."""
    help_lines = [
        ("--- Client Help ---", curses.color_pair(4) | curses.A_BOLD), # Green Bold Header
        (" /help         - Show this help message", 4),                 # Green
        (" /clear        - Clear non-user/server messages", 4),
        (" /clearall     - Clear ALL messages from chat", 4),
        (" /toggle_sound - Toggle notification sound on/off", 4),
        (" /status       - Show current user and sound status", 4),
        (" /exit         - Disconnect from the server", 4),
        ("--- Server Commands (Sent to Server) ---", curses.color_pair(4) | curses.A_BOLD),
        (" /list         - List connected users", 4),
        (" /files <user> - List files uploaded by <user>", 4),
        (" /upload <path>- Request to upload a file (Server support needed)", 4),
        (" /download <user> <filename> - Request to download a file", 4),
        (" /delete <filename> - Request deletion of your own file", 4),
        ("--- Operator Only Server Commands ---", curses.color_pair(4) | curses.A_BOLD),
        (" /kick <user> [reason]", 4),
        (" /op <user>", 4),
        (" /deop <user>", 4),
        (" /listops", 4),
        (" /delete <user> <filename>", 4),
        (" /stop /restart", 4),
        ("--- TUI Navigation ---", curses.color_pair(4) | curses.A_BOLD),
        (" PgUp / PgDn   - Scroll chat history", 4),
        (" Ctrl+C        - Force quit the client (tries graceful exit)", 4),
        ("-------------------", curses.color_pair(4) | curses.A_BOLD) # Green Bold Footer
    ]
    # Add each line with its specified attribute and no sound
    for line, attr in help_lines:
        add_message(line, attr, play_sound=False)


def process_user_command(command_text, sock):
    """Handles purely client-side commands OR sends others to the server."""
    global NOTIFICATION_SOUND_ACTIVE, messages, _intentional_exit # Access globals

    parts = command_text.strip().split(" ", 1)
    command = parts[0].lower()

    # --- Purely Client-Side Commands ---
    if command == "/clear":
        with message_lock:
            # Keep only user's own messages (color 1, bold) and incoming (color 2)
            messages[:] = [msg for msg in messages if msg[1] == (curses.color_pair(1) | curses.A_BOLD) or msg[1] == curses.color_pair(2)]
        add_message("Client-side messages cleared.", 6, play_sound=False) # Yellow status
        needs_redraw.set()
        return True # Continue running client
    elif command == "/clearall":
        with message_lock:
            messages.clear()
        add_message("All messages cleared.", 6, play_sound=False) # Yellow status
        needs_redraw.set()
        return True # Continue running client
    elif command == "/toggle_sound":
        if SOUND_ENABLED:
            NOTIFICATION_SOUND_ACTIVE = not NOTIFICATION_SOUND_ACTIVE
            save_sound_setting(NOTIFICATION_SOUND_ACTIVE)
            state = "ON" if NOTIFICATION_SOUND_ACTIVE else "OFF"
            add_message(f"Sound notifications turned {state}.", 4, play_sound=False) # Green info
        else:
            add_message("Sound library (playsound) not available.", 3, play_sound=False) # Red error
        needs_redraw.set() # Update status bar via redraw
        return True # Continue running client
    elif command == "/status":
        sound_state = "ON" if NOTIFICATION_SOUND_ACTIVE else "OFF"
        if not SOUND_ENABLED: sound_state = "N/A"
        add_message(f"Status: User='{CURRENT_USER}', Sound={sound_state}", 4, play_sound=False) # Green info
        return True # Continue running client
    elif command == "/help":
        show_client_help()
        return True # Continue running client

    # --- Commands to Send to Server ---
    else:
        if sock is None:
            # Check if we are waiting for reconnect ack. If so, the command is likely invalid input.
            if waiting_for_reconnect_ack:
                add_message("Invalid input. Please enter 'y' or 'n'.", 3, play_sound=False)
            else:
                add_message("Not connected to server.", 3, play_sound=False)
            return True # Cannot send command, but client keeps running

        try:
            # Send the raw command text to the server
            sock.sendall(command_text.encode("utf-8"))

            # If the command was /exit, signal loop termination *after* sending
            if command == "/exit":
                _intentional_exit = True # Set flag *before* returning False
                add_message("Disconnecting...", 6, play_sound=False) # Yellow status
                return False # Tells the main loop to stop

            # For other commands sent to server, client continues running
            return True

        except OSError as e:
            add_message(f"Error sending command '{command_text}': {e}", 3, play_sound=False) # Red error
            # If exit command itself fails, still try to terminate client loop locally
            if command == "/exit":
                _intentional_exit = True # Set flag even on error
                return False # Stop client loop
            return True # Continue client loop despite send error for other commands
        except Exception as e:
            add_message(f"Unexpected error sending command '{command_text}': {e}", 3, play_sound=False)
            if command == "/exit":
                _intentional_exit = True # Set flag even on error
                return False # Stop client loop
            return True


def send_message(sock, text):
    """Sends a regular message OR calls command processor."""
    if not text: return True # Do nothing if input is empty

    if text.startswith("/"):
        # Process as command, returns False if client should exit (e.g., /exit)
        return process_user_command(text, sock)
    else: # Regular message
        if sock is None:
             # Check if we are waiting for reconnect ack. If so, the command is likely invalid input.
            if waiting_for_reconnect_ack:
                add_message("Invalid input. Please enter 'y' or 'n'.", 3, play_sound=False)
            else:
               add_message("Cannot send message: Not connected.", 3, play_sound=False)
            return True # Client continues running

        if len(text) > MAX_LENGHT:
            add_message(f"Message too long (max {MAX_LENGHT} chars). Not sent.", 3, play_sound=False) # Red error
            return True # Continue running

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        display_msg = f"{timestamp} [{CURRENT_USER}]: {text}"
        # Add user's own message (Magenta=1, Bold), no sound for own messages
        add_message(display_msg, curses.color_pair(1) | curses.A_BOLD, play_sound=False)

        try:
            sock.sendall(text.encode("utf-8"))
            return True # Message sent successfully, continue running
        except OSError as e:
            add_message(f"Error sending message: {e}", 3, play_sound=False)
            # Don't exit client, maybe connection will recover or user wants to /exit
            return True # Log error, continue
        except Exception as e:
            add_message(f"Unexpected error sending: {e}", 3, play_sound=False)
            return True # Log error, continue


def get_string_input(stdscr, prompt_y, prompt_text, is_password=False):
    """Helper function to get string input robustly within curses."""
    # Clear the line, add prompt
    stdscr.move(prompt_y, 0)
    stdscr.clrtoeol()
    stdscr.addstr(prompt_y, 0, prompt_text + " ")

    if is_password:
        curses.noecho() # Don't display password characters
    else:
        curses.echo() # Display typed characters

    curses.curs_set(1) # Show cursor
    stdscr.refresh()

    # Enable blocking getstr for these initial prompts
    stdscr.nodelay(False)
    stdscr.timeout(-1) # Wait indefinitely for input

    # Get input string directly
    input_str = stdscr.getstr().decode('utf-8').strip()

    # Clean up after input
    curses.noecho() # Ensure echo is off afterwards
    curses.curs_set(0) # Hide cursor again for main UI
    stdscr.move(prompt_y, 0) # Move back to prompt line start
    stdscr.clrtoeol() # Clear the prompt and input for security (esp. password)
    stdscr.refresh()

    # Restore non-blocking mode for the main loop (will be set in client_main)
    # stdscr.nodelay(True)
    # stdscr.timeout(INPUT_TIMEOUT)

    return input_str

# --- MODIFIED attempt_connection ---
def attempt_connection(stdscr, ip, port, server_pw_saved, username_saved, user_pw_saved, auto_reconnect=False):
    """
    Attempts to connect to the server and authenticate or register.
    Handles prompting for credentials if not provided or if saved ones fail,
    *unless* auto_reconnect is True, in which case it uses saved credentials only.
    Returns the connected socket on success, None on failure.
    'auto_reconnect' flag influences password prompting logic.
    """
    global CURRENT_USER, needs_redraw # We need to set CURRENT_USER on successful login

    sock = None
    # Use copies of saved credentials
    temp_server_pw = server_pw_saved
    temp_username = username_saved
    temp_user_pw = user_pw_saved # This might be None
    password_used_for_auth = "" # Holds the password actually sent and accepted

    try:
        # --- Check for required data during auto-reconnect ---
        if auto_reconnect:
            # All details MUST be present in the saved session for auto-reconnect
            if not ip or not isinstance(port, int) or not (1 <= port <= 65535) or not temp_server_pw or not temp_username or temp_user_pw is None:
                add_message("Cannot auto-reconnect: Incomplete session data.", 3, play_sound=False)
                needs_redraw.set()
                return None # Fail immediately without prompting

        # --- Connect ---
        add_message(f"Connecting to {ip}:{port}...", 6, play_sound=False)
        needs_redraw.set()
        if stdscr:
            try: stdscr.refresh()
            except: pass
        time.sleep(0.1)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        sock.connect((ip, port))
        sock.settimeout(None) # Switch to blocking after connection
        add_message("Connected. Authenticating...", 6, play_sound=False)
        needs_redraw.set()
        if stdscr:
            try: stdscr.refresh()
            except: pass

        # --- Authentication/Registration Steps ---

        # 1. Server Password
        server_prompt_bytes = sock.recv(1024)
        if not server_prompt_bytes: raise ConnectionAbortedError("Server closed connection (before server password prompt).")
        server_prompt = server_prompt_bytes.decode("utf-8", errors='replace').strip()

        # Prompt only if not provided AND NOT auto-reconnecting
        if not temp_server_pw and not auto_reconnect:
            if not stdscr: raise RuntimeError("stdscr required for password prompt.")
            temp_server_pw = get_string_input(stdscr, curses.LINES - 1, strip_ansi_codes(server_prompt), is_password=True)
            needs_redraw.set() # Redraw whole UI after prompt clears
        elif not temp_server_pw and auto_reconnect:
            # Should have been caught by the initial check, but safeguard here.
            raise ConnectionAbortedError("Auto-reconnect failed: Missing server password.")

        sock.sendall(temp_server_pw.encode("utf-8"))

        # 2. Username
        user_prompt_bytes = sock.recv(1024)
        if not user_prompt_bytes: raise ConnectionAbortedError("Server closed connection (before username prompt).")
        user_prompt = user_prompt_bytes.decode("utf-8", errors='replace').strip()

        # Prompt only if not provided AND NOT auto-reconnecting
        if not temp_username and not auto_reconnect:
            if not stdscr: raise RuntimeError("stdscr required for username prompt.")
            temp_username = get_string_input(stdscr, curses.LINES - 1, strip_ansi_codes(user_prompt), is_password=False) # Echo username
            needs_redraw.set()
        elif not temp_username and auto_reconnect:
            # Should have been caught, safeguard.
            raise ConnectionAbortedError("Auto-reconnect failed: Missing username.")

        sock.sendall(temp_username.encode("utf-8"))
        # Don't set global CURRENT_USER until login/registration is confirmed successful

        # 3. Receive Next Prompt (Could be for Password or Registration)
        next_prompt_bytes = sock.recv(1024)
        if not next_prompt_bytes: raise ConnectionAbortedError("Server closed connection (before user password/registration prompt).")
        next_prompt = next_prompt_bytes.decode("utf-8", errors='replace').strip()

        # --- Check if it's a Registration prompt ---
        if "new_password:new_password" in next_prompt:
            # --- REGISTRATION PATH ---
            add_message("Username not found on server. Registering...", 6, play_sound=False)
            needs_redraw.set()
            if stdscr: stdscr.refresh()

            if auto_reconnect:
                # This shouldn't happen if credentials were correct for auto-reconnect
                raise ConnectionAbortedError("Auto-reconnect failed: Server prompted for registration unexpectedly.")
            if not stdscr:
                raise RuntimeError("stdscr required for registration password prompt.")

            # Prompt for new password twice
            new_pass1 = get_string_input(stdscr, curses.LINES - 1, "Enter new password:", is_password=True)
            needs_redraw.set() # Redraw UI to show next prompt cleanly
            if not new_pass1: # User likely cancelled or entered nothing
                 add_message("Password cannot be empty. Registration cancelled.", 3, play_sound=False)
                 raise ConnectionAbortedError("Registration cancelled by user (empty password).")

            new_pass2 = get_string_input(stdscr, curses.LINES - 1, "Confirm new password:", is_password=True)
            needs_redraw.set() # Redraw UI after last prompt

            if new_pass1 == new_pass2:
                # Passwords match, send in required format
                registration_payload = f"{new_pass1}:{new_pass2}"
                password_used_for_auth = new_pass1 # Store the password for potential saving
                sock.sendall(registration_payload.encode("utf-8"))
                add_message("Registration details sent. Waiting for confirmation...", 6, play_sound=False)
                needs_redraw.set()
            else:
                # Passwords don't match
                add_message("Passwords do not match. Registration failed.", 3, play_sound=False)
                raise ConnectionAbortedError("Registration failed (password mismatch).")

        else:
            # --- NORMAL LOGIN PATH (Existing User) ---
            login_password_to_send = "" # Holds the user password actually sent in this path

            # Determine if we use saved password or need to prompt
            prompt_for_user_password = True
            if auto_reconnect and temp_user_pw is not None:
                login_password_to_send = temp_user_pw
                prompt_for_user_password = False
            elif not auto_reconnect and temp_user_pw is not None:
                 # Check if the saved password should be used or if user wants to re-enter
                 # For simplicity, we'll use the saved one if available on initial connect
                 # A more complex UI could ask 'Use saved password? (y/n)' here.
                 login_password_to_send = temp_user_pw
                 prompt_for_user_password = False # Assume using saved if available initially
            elif auto_reconnect and temp_user_pw is None:
                 # Should have been caught, safeguard.
                 raise ConnectionAbortedError("Auto-reconnect failed: Missing user password for login.")
            # Else (initial connect, no password saved) -> prompt_for_user_password remains True

            # Prompt if needed (only initial connect with no saved password, or if logic above dictates)
            if prompt_for_user_password:
                # This block should only be reachable if auto_reconnect is False and temp_user_pw was None
                if auto_reconnect: # Defensive check
                    raise ConnectionAbortedError("Auto-reconnect logic error: Tried to prompt for login password.")
                if not stdscr: raise RuntimeError("stdscr required for user password prompt.")
                # Use the prompt we received from the server
                login_password_to_send = get_string_input(stdscr, curses.LINES - 1, strip_ansi_codes(next_prompt), is_password=True)
                needs_redraw.set()

            # Send the password
            password_used_for_auth = login_password_to_send # Store the password for potential saving
            sock.sendall(login_password_to_send.encode("utf-8"))


        # 4. Check Final Login/Registration Response
        final_response_bytes = sock.recv(1024)
        if not final_response_bytes: raise ConnectionAbortedError("Server closed connection after password/registration submission.")
        final_response = final_response_bytes.decode("utf-8", errors='replace').strip()

        # Check for either success message
        if "Login successful" not in final_response and "Registration successful" not in final_response:
            # Clean up the server response message for display
            cleaned_response = strip_ansi_codes(final_response).replace('\n', ' ').strip()
            raise ConnectionAbortedError(f"Login/Registration Failed: {cleaned_response}")

        # --- Login or Registration Successful ---
        CURRENT_USER = temp_username # Set global username NOW
        success_message = "Login successful" if "Login successful" in final_response else "Registration successful"
        add_message(f"{success_message}. Welcome {CURRENT_USER}!", 4, play_sound=False)

        # Save session details (always save on successful login/registration)
        # Use password_used_for_auth which was set in the appropriate path above
        save_session(ip, port, temp_server_pw, temp_username, password_used_for_auth)

        needs_redraw.set()
        return sock # Return the connected and authenticated socket

    except (socket.error, OSError, EOFError, ConnectionAbortedError, RuntimeError) as e:
        # Handle connection, authentication, prompting, or registration errors
        add_message(f"Connection/Auth/Reg Failed: {e}", 3, play_sound=False)
        if sock:
            try: sock.close()
            except: pass
        needs_redraw.set()
        if stdscr:
            try:
                curses.noecho()
                curses.curs_set(0)
            except: pass
        return None # Indicate failure
    except Exception as e: # Catch any other unexpected errors
        add_message(f"Unexpected Connection Error: {e}", 3, play_sound=False)
        # Consider adding full traceback logging here for debugging
        # import traceback
        # traceback.print_exc()
        if sock:
            try: sock.close()
            except: pass
        needs_redraw.set()
        if stdscr:
            try:
                curses.noecho()
                curses.curs_set(0)
            except: pass
        return None # Indicate failure


# --- MODIFIED client_main (to handle reconnect prompt logic) ---

def client_main(stdscr):
    """The main function orchestrating the TUI client."""
    global client_socket, CURRENT_USER, messages, _intentional_exit, needs_redraw, waiting_for_reconnect_ack

    # Reset global state variables at the start of execution
    _intentional_exit = False
    waiting_for_reconnect_ack = False # Reset reconnect prompt flag
    messages.clear() # Clear messages from previous runs
    CURRENT_USER = ""
    client_socket = None

    # --- Initial Curses Setup ---
    curses.curs_set(0) # Hide cursor initially
    try:
        init_colors()
    except curses.error as e:
        print(f"Terminal color initialization failed: {e}", file=sys.stderr)
        print("Try setting TERM environment variable (e.g., export TERM=xterm-256color)", file=sys.stderr)
        return # Cannot proceed without colors

    load_sound_setting() # Load sound preference
    stdscr.keypad(True)  # Enable special keys
    stdscr.nodelay(False) # Start with blocking for initial connection input
    stdscr.timeout(-1)   # Wait indefinitely for initial input
    curses.noecho()      # Don't echo typed characters by default

    # --- Get Connection Details ---
    session = load_session()
    initially_used_session = False
    server_ip, server_port, server_password, username, user_password = "", 0, "", "", None

    stdscr.clear()
    if session:
        try:
            # Display saved session info
            stdscr.addstr(0, 0, "Found saved session:\n")
            stdscr.addstr(f"  IP: {session.get('server_ip', 'N/A')}\n")
            stdscr.addstr(f"  Port: {session.get('server_port', 'N/A')}\n")
            stdscr.addstr(f"  Server PW Saved: {'Yes' if session.get('server_password') else 'No'}\n")
            stdscr.addstr(f"  Username: {session.get('username', 'N/A')}\n")
            stdscr.addstr(f"  User PW Saved: {'Yes' if session.get('user_password') is not None else 'No'}\n")
            stdscr.addstr("\nUse this session? (y/n): ")

            curses.echo(); curses.curs_set(1); stdscr.refresh()

            while True:
                key = stdscr.getch() # Blocking call
                if key in (ord('y'), ord('Y')):
                    initially_used_session = True
                    server_ip = session.get('server_ip', "")
                    server_port = session.get('server_port', 0)
                    server_password = session.get('server_password', "")
                    username = session.get('username', "")
                    user_password = session.get('user_password')
                    break
                elif key in (ord('n'), ord('N')):
                    initially_used_session = False
                    break

            curses.noecho(); curses.curs_set(0)
            stdscr.clear(); stdscr.refresh()

        except curses.error as e:
            print(f"Error during session prompt (terminal too small?): {e}", file=sys.stderr)
            return # Exit client

    # --- Prompt for Details if Not Using Session or Session Incomplete ---
    if not initially_used_session or not server_ip:
        server_ip = get_string_input(stdscr, 0, "Enter Server IP:")
        while not server_ip:
            stdscr.addstr(1, 0, "IP Address cannot be empty.", curses.A_REVERSE)
            server_ip = get_string_input(stdscr, 0, "Enter Server IP:")
            stdscr.move(1, 0); stdscr.clrtoeol()

    if not initially_used_session or not isinstance(server_port, int) or not (1 <= server_port <= 65535):
        server_port = 0
        while not (1 <= server_port <= 65535):
            port_str = get_string_input(stdscr, 1, "Enter Server Port (1-65535):")
            try:
                server_port = int(port_str)
                if not (1 <= server_port <= 65535):
                    stdscr.addstr(2, 0, "Port must be between 1 and 65535.", curses.A_REVERSE)
                    server_port = 0
            except ValueError:
                stdscr.addstr(2, 0, "Invalid port number. Please enter digits only.", curses.A_REVERSE)
                server_port = 0
            stdscr.refresh()
            if not (1 <= server_port <= 65535):
                time.sleep(1)
                stdscr.move(2, 0); stdscr.clrtoeol()

    stdscr.move(0,0); stdscr.clrtoeol()
    stdscr.move(1,0); stdscr.clrtoeol()
    stdscr.move(2,0); stdscr.clrtoeol()
    stdscr.refresh()
    curses.noecho(); curses.curs_set(0)

    # --- Initial Connection Attempt ---
    stdscr.clear(); stdscr.refresh()
    client_socket = attempt_connection(
        stdscr, server_ip, server_port,
        server_password, username, user_password,
        auto_reconnect=False # This is the initial connection
    )

    if not client_socket:
        max_y, max_x = stdscr.getmaxyx()
        try:
            temp_chat_h = max(1, max_y - 1)
            temp_chat = curses.newwin(temp_chat_h, max_x, 0, 0)
            temp_chat.scrollok(True)
            redraw_chat(temp_chat, 0) # Draw messages collected so far
            stdscr.addstr(max_y - 1, 0, "Connection failed. Press any key to exit.")
        except curses.error: pass

        stdscr.nodelay(False); stdscr.timeout(-1); curses.curs_set(0)
        try:
            stdscr.getch() # Wait for key press
        except curses.error: pass
        return # Exit client_main function

    # --- Setup Main UI Windows ---
    curses.curs_set(1) # Show cursor in input window
    curses.noecho()    # Ensure echo is off for main input
    stdscr.nodelay(True) # Set non-blocking input for the main loop
    stdscr.timeout(INPUT_TIMEOUT) # Check for input every INPUT_TIMEOUT ms

    max_y, max_x = stdscr.getmaxyx()
    try:
        chat_win, input_win, status_win = create_windows(max_y, max_x)
    except curses.error as e:
        print(f"Terminal too small for UI: {e}. Please resize.", file=sys.stderr)
        if client_socket:
            _intentional_exit = True
            try: client_socket.sendall(b"/exit")
            except: pass
            try: client_socket.close()
            except: pass
            client_socket = None
        return # Exit client_main

    # --- Start Receiver Thread ---
    receiver = threading.Thread(target=receive_messages_thread, args=(client_socket,), daemon=True)
    receiver.start()

    # --- Main Event Loop ---
    current_input = ""
    scroll_pos = 0 # 0 means scrolled to the bottom
    running = True
    needs_redraw.set() # Trigger initial draw of the UI

    while running:
        # --- Redrawing ---
        if needs_redraw.is_set():
            needs_redraw.clear()
            stdscr.clearok(True)
            stdscr.clear()

            try:
                # Redraw all windows
                redraw_status(status_win)
                redraw_chat(chat_win, scroll_pos)
                # Redraw input MUST come last to position cursor correctly
                redraw_input(input_win, current_input)
            except curses.error:
                # Attempt to resize UI components
                new_windows = resize_ui(stdscr, chat_win, input_win, status_win)
                if new_windows[0]:
                    chat_win, input_win, status_win = new_windows
                    needs_redraw.set() # Force redraw with new windows
                else:
                    running = False
                    _intentional_exit = True
                    print("Terminal too small, exiting.", file=sys.stderr)
                continue # Restart loop after resize attempt

            stdscr.clearok(False)
            # Cursor positioning is now handled within redraw_input


        # --- Input Handling ---
        try:
            input_win.timeout(INPUT_TIMEOUT) # Ensure timeout is set for the input window
            key = input_win.getch()
        except curses.error: # Error getting input, maybe terminal closed/unusable?
            running = False
            _intentional_exit = True
            print("Error reading input, exiting.", file=sys.stderr)
            continue

        # --- Check Receiver Thread Status & Handle Reconnect Prompt ---
        # >>> MODIFIED BLOCK START <<<
        if not receiver.is_alive() and not _intentional_exit and not waiting_for_reconnect_ack:
            # Receiver thread died unexpectedly (network error, server closed connection)
            # AND we are not already waiting for the user's decision.
            if client_socket: # Clean up old socket reference
                try: client_socket.close()
                except: pass
                client_socket = None

            # Display "Connection lost." message
            add_message("Connection lost.", 3, play_sound=False) # Use Red color

            # Set flag to wait for user input 'y' or 'n'
            waiting_for_reconnect_ack = True
            current_input = "" # Clear any partial user input
            needs_redraw.set() # Trigger redraw to show the prompt
            continue # Skip normal input processing, wait for y/n

        # >>> MODIFIED BLOCK END <<<

        # --- Process Input Key ---
        if key == -1:
            # No input within timeout, just continue loop
            continue

        # --- Handle Input WHILE waiting for reconnect confirmation ---
        if waiting_for_reconnect_ack:
            if key in (ord('y'), ord('Y')):
                waiting_for_reconnect_ack = False # Reset flag
                add_message("Attempting reconnection...", 6, play_sound=False)
                needs_redraw.set() # Show the "Attempting..." message

                # Need current session data for reconnection
                current_session = load_session()
                if current_session:
                    reconnect_ip = current_session.get('server_ip')
                    reconnect_port = current_session.get('server_port')
                    reconnect_server_pw = current_session.get('server_password')
                    reconnect_username = current_session.get('username')
                    reconnect_user_pw = current_session.get('user_password')

                    # Call attempt_connection with auto_reconnect=True
                    client_socket = attempt_connection(
                        stdscr, reconnect_ip, reconnect_port,
                        reconnect_server_pw, reconnect_username, reconnect_user_pw,
                        auto_reconnect=True # IMPORTANT FLAG
                    )
                else:
                    add_message("Cannot reconnect: Failed to load session data.", 3, play_sound=False)
                    client_socket = None

                if client_socket:
                    # Reconnection Success!
                    add_message("Reconnected successfully!", 4, play_sound=True)
                    _intentional_exit = False # Reset flag
                    # Start new receiver thread
                    receiver = threading.Thread(target=receive_messages_thread, args=(client_socket,), daemon=True)
                    receiver.start()
                else:
                    # Reconnection failed
                    add_message("Reconnection failed. Exiting.", 3, play_sound=False)
                    running = False # Exit main loop
                    _intentional_exit = True # Mark as intentional now

                needs_redraw.set() # Redraw UI

            elif key in (ord('n'), ord('N')):
                waiting_for_reconnect_ack = False # Reset flag
                add_message("Not reconnecting. Exiting.", 6, play_sound=False)
                running = False # Exit main loop
                _intentional_exit = True # Mark as intentional exit
                needs_redraw.set() # Redraw UI

            else:
                # Ignore other keys while waiting for y/n
                # Optional: add a small bell/flash?
                curses.beep()
                pass
            # After handling y/n or ignoring other keys, continue to next loop iteration
            continue

        # --- Process Input Key (Normal Operation - NOT waiting for reconnect ack) ---
        if key == curses.KEY_RESIZE:
            new_windows = resize_ui(stdscr, chat_win, input_win, status_win)
            if new_windows[0]:
                chat_win, input_win, status_win = new_windows
                needs_redraw.set() # Force redraw
            else: # Resize failed badly
                running = False; _intentional_exit = True
                print("Terminal too small after resize, exiting.", file=sys.stderr)
            continue # Restart loop after resize attempt

        elif key in (curses.KEY_BACKSPACE, 127, 8): # Handle various backspace keys
            current_input = current_input[:-1]
            redraw_input(input_win, current_input) # Redraw only input needed

        elif key in (curses.KEY_ENTER, 10, 13): # Handle various enter keys
            input_to_send = current_input.strip()
            current_input = "" # Clear input buffer immediately
            scroll_pos = 0 # Scroll to bottom after sending
            # redraw_input is handled by needs_redraw.set() below

            if input_to_send: # Only process if there was actual input
                running = send_message(client_socket, input_to_send)
                if not running: # If send_message returned False (due to /exit)
                    _intentional_exit = True

            needs_redraw.set() # Redraw after sending/processing

        elif key == curses.KEY_PPAGE: # Page Up
            chat_h = chat_win.getmaxyx()[0]
            scroll_amount = max(1, chat_h - 3)
            with message_lock:
                # Calculate effective number of lines (consider wrapping later if needed)
                # For now, assume 1 message = 1 line for scroll calculation simplicity
                visible_lines = max(1, chat_h - 2)
                max_scroll = max(0, len(messages) - visible_lines)
            scroll_pos = min(scroll_pos + scroll_amount, max_scroll)
            needs_redraw.set()

        elif key == curses.KEY_NPAGE: # Page Down
            chat_h = chat_win.getmaxyx()[0]
            scroll_amount = max(1, chat_h - 3)
            scroll_pos = max(0, scroll_pos - scroll_amount)
            needs_redraw.set()

        elif 32 <= key <= 255: # Printable characters (Basic ASCII range)
             if len(current_input) < MAX_LENGHT + 50: # Allow some buffer over limit
                 try:
                     current_input += chr(key)
                     redraw_input(input_win, current_input) # Redraw only input window
                 except ValueError:
                     pass # Ignore invalid chars

        # Ignore other special keys for now

    # --- End of Main Loop ---
    # This block runs when running becomes False

    # Final redraw attempt to show disconnection messages before exit
    if needs_redraw.is_set() or not _intentional_exit:
       if not _intentional_exit and not waiting_for_reconnect_ack:
           # If exiting due to loop end without explicit /exit or Ctrl+C
           # and not already waiting for reconnect prompt (which means failure occurred)
            add_message("Disconnecting...", 6, play_sound=False)
       try:
           # Ensure cursor is hidden on final draw
           curses.curs_set(0)
           # Need to redraw chat to show final messages
           if 'chat_win' in locals() and chat_win: redraw_chat(chat_win, scroll_pos)
           # Need to redraw status bar
           if 'status_win' in locals() and status_win: redraw_status(status_win)
           # Optionally clear the input line on exit
           if 'input_win' in locals() and input_win:
               input_win.erase()
               input_win.border()
               input_win.refresh()
           stdscr.refresh()
       except: pass
       time.sleep(0.5) # Short pause to see final state


# --- Signal Handler & Exit Cleanup ---

def graceful_exit_handler(signum, frame):
    """Attempts to gracefully close the connection on SIGINT (Ctrl+C)."""
    global client_socket, _exiting_gracefully, _intentional_exit
    if _exiting_gracefully: return # Already handling exit
    _exiting_gracefully = True
    _intentional_exit = True # Mark exit as intentional

    try:
        if curses and not curses.isendwin():
            # Use add_message if possible, redraw might be needed manually
            add_message("Ctrl+C detected. Sending /exit...", 3, play_sound=False)
            # Force a basic redraw attempt if possible
            try:
                # Get screen dimensions directly if possible
                max_y, max_x = curses.LINES, curses.COLS
                # Minimal redraw - just show the message at bottom left maybe
                curses.movestr(max_y -1, 0, "Ctrl+C detected. Exiting...")
                curses.refresh()
            except: pass # Ignore errors if curses is unusable
            time.sleep(0.2) # Short delay
        else:
            print("\nCtrl+C detected. Exiting...", file=sys.stderr) # Fallback print
    except:
        print("\nCtrl+C detected. Exiting...", file=sys.stderr) # Fallback print

    sock_to_close = client_socket
    client_socket = None # Prevent main loop/receiver from using it further

    if sock_to_close:
        try:
            sock_to_close.sendall("/exit".encode("utf-8"))
            time.sleep(0.1) # Give server a moment
        except: pass
        try: sock_to_close.shutdown(socket.SHUT_RDWR)
        except: pass
        try: sock_to_close.close()
        except: pass

    # Explicitly call cleanup registered with atexit, as signal might bypass normal exit
    cleanup()

    # Force exit after cleanup attempt
    sys.exit(0)


original_excepthook = sys.excepthook
def custom_excepthook(type, value, tb):
    """Ensures curses is ended before printing traceback."""
    # Ensure cleanup runs even on unhandled exceptions
    cleanup()
    print("\n--- UNCAUGHT EXCEPTION ---", file=sys.stderr)
    original_excepthook(type, value, tb)
    print("--------------------------", file=sys.stderr)
    if sys.platform != "win32":
        try: os.system('reset') # Try resetting terminal on non-Windows
        except: pass

_cleanup_called = False
def cleanup():
    """Final cleanup actions to run on normal exit or unhandled exception."""
    global client_socket, _cleanup_called
    if _cleanup_called: return # Prevent double execution
    _cleanup_called = True

    # --- Ensure Curses is ended ---
    try:
        if curses and not curses.isendwin():
            curses.echo()
            curses.nocbreak()
            curses.keypad(False)
            curses.endwin()
            # print("Curses ended by cleanup.", file=sys.stderr) # Optional debug
    except Exception as e:
        # print(f"Error ending curses in cleanup: {e}", file=sys.stderr) # Optional debug
        pass # Ignore errors during cleanup

    # --- Close socket if still open ---
    sock = client_socket
    if sock:
        # print("Attempting socket close in cleanup...", file=sys.stderr) # Optional debug
        try: sock.shutdown(socket.SHUT_RDWR)
        except: pass
        try:
            sock.close()
            client_socket = None
            # print("Socket closed by cleanup.", file=sys.stderr) # Optional debug
        except: pass
    # print("Client cleanup finished.") # Final message after cleanup

# --- Entry Point ---
if __name__ == "__main__":
    sys.excepthook = custom_excepthook
    atexit.register(cleanup)
    # Register SIGINT handler AFTER atexit to ensure cleanup runs
    signal.signal(signal.SIGINT, graceful_exit_handler)
    # Optionally handle SIGTERM for graceful shutdown requests
    # signal.signal(signal.SIGTERM, graceful_exit_handler)

    try:
        ensure_settings_dir()
        curses.wrapper(client_main)

    except curses.error as e:
        # Curses errors often leave terminal messed up
        print(f"\nCurses error occurred (likely terminal related): {e}", file=sys.stderr)
        if sys.platform != "win32":
            try: os.system('reset')
            except: pass
        print("Exiting due to curses error.", file=sys.stderr)
        sys.exit(1) # Indicate error exit
    except KeyboardInterrupt:
        # Should be caught by signal handler, but added as failsafe
        print("\nKeyboardInterrupt caught in main block (should have been handled).", file=sys.stderr)
    except Exception as e:
        # Exception hook should handle this, but added as failsafe
        print(f"\nUnexpected error in main execution block: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1) # Indicate error exit

    # print("Client exiting normally.") # Message for clean exit path
    sys.exit(0) # Indicate clean exit
