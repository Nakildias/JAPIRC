import socket
import threading
import curses
import datetime
import re
from playsound import playsound
import json
import os
import time
import signal
import sys

MAX_LENGHT = 150  # Maximum Character Clients Can Send / Needs to match the server (Default: 150)
CURRENT_USER = ""

# Setting files
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
SOUND_FILE = "sound_option.json"

def load_sound_setting():
    try:
        with open(SOUND_FILE, "r") as file:
            return json.load(file).get("notification_sound", True)
    except (FileNotFoundError, json.JSONDecodeError):
        return True

def save_sound_setting(value):
    with open(SOUND_FILE, "w") as file:
        json.dump({"notification_sound": value}, file)

NOTIFICATION_SOUND = load_sound_setting()

def init_colors():
    curses.start_color()
    curses.init_pair(1, curses.COLOR_MAGENTA, curses.COLOR_BLACK)  # User messages
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Server messages
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)  # Errors or warnings
    curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Status messages

def strip_ansi_codes(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def play_sound_in_background(sound_file):
    if NOTIFICATION_SOUND:
        try:
            threading.Thread(target=playsound, args=(sound_file,), daemon=True).start()
        except RuntimeError:
            pass

def receive_messages(client_socket, messages, lock, chat_win, scroll_pos):
    global NOTIFICATION_SOUND
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                break

            message = strip_ansi_codes(message)

            # Check for file transfer header
            if message.startswith("FILE_TRANSFER:"):
                _, filename, file_size = message.strip().split(":")
                file_size = int(file_size)

                messages.append(("Starting Download.", 4))

                save_path = os.path.join(DOWNLOAD_DIR, filename)
                with open(save_path, "wb") as file:
                    bytes_received = 0
                    while bytes_received < file_size:
                        chunk = client_socket.recv(1024)
                        if not chunk:
                            break
                        file.write(chunk)
                        bytes_received += len(chunk)

                messages.append(("File Downloaded.", 4))
                continue  # Skip normal message handling

            with lock:
                if NOTIFICATION_SOUND:
                    play_sound_in_background('notification.wav')
                messages.append((message, 2))
                if scroll_pos == 0:
                    redraw_chat(chat_win, messages, scroll_pos)
        except:
            with lock:
                messages.append(("Connection lost.", 3))
            break

def redraw_chat(chat_win, messages, scroll_pos):
    chat_win.clear()  # **Force clear screen to prevent corruption**
    chat_win.refresh()  # **Ensure full reset before drawing**

    max_y, _ = chat_win.getmaxyx()
    start = max(0, len(messages) - max_y + scroll_pos)
    end = start + max_y

    for i, (msg, color) in enumerate(messages[start:end]):
        try:
            chat_win.addstr(i, 0, msg[:MAX_LENGHT], curses.color_pair(color))
        except curses.error:
            pass  # Ignore screen size errors

    chat_win.refresh()

def resize_windows(stdscr, chat_win, input_win, status_win):
    max_y, max_x = stdscr.getmaxyx()
    chat_win.resize(max_y - 3, max_x)
    input_win.resize(1, max_x)
    status_win.resize(1, max_x)
    chat_win.mvwin(0, 0)
    input_win.mvwin(max_y - 2, 0)
    status_win.mvwin(max_y - 1, 0)

def graceful_exit(signal, frame, client_socket):
    print("Closing connection gracefully...")
    client_socket.close()
    sys.exit(0)

def client(stdscr):
    global CURRENT_USER, NOTIFICATION_SOUND
    curses.use_default_colors()
    curses.curs_set(1)
    stdscr.clear()
    stdscr.refresh()
    stdscr.keypad(True)
    init_colors()

    max_y, max_x = stdscr.getmaxyx()
    chat_win = curses.newwin(max_y - 3, max_x, 0, 0)
    input_win = curses.newwin(1, max_x, max_y - 2, 0)
    status_win = curses.newwin(1, max_x, max_y - 1, 0)

    messages = []
    lock = threading.Lock()
    scroll_pos = 0
    command_output = []

    curses.echo()
    stdscr.addstr(0, 0, "Enter server IP: ")
    stdscr.refresh()
    server_ip = stdscr.getstr().decode("utf-8")
    stdscr.addstr(1, 0, "Enter server Port: ")
    stdscr.refresh()
    server_port = int(stdscr.getstr().decode("utf-8"))

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((server_ip, server_port))

    stdscr.addstr(2, 0, strip_ansi_codes(client_socket.recv(1024).decode("utf-8")), curses.color_pair(2))
    curses.noecho()
    stdscr.refresh()
    server_password = stdscr.getstr().decode("utf-8")
    client_socket.send(server_password.encode("utf-8"))

    stdscr.addstr(3, 0, strip_ansi_codes(client_socket.recv(1024).decode("utf-8")), curses.color_pair(2))
    curses.echo()
    stdscr.refresh()
    username = stdscr.getstr().decode("utf-8")
    client_socket.send(username.encode("utf-8"))
    CURRENT_USER = username

    stdscr.refresh()
    curses.noecho()
    stdscr.addstr(4, 0, strip_ansi_codes(client_socket.recv(1024).decode("utf-8")), curses.color_pair(2))
    password = stdscr.getstr().decode("utf-8")
    client_socket.send(password.encode("utf-8"))

    curses.noecho()
    receive_thread = threading.Thread(target=receive_messages, args=(client_socket, messages, lock, chat_win, scroll_pos), daemon=True)
    receive_thread.start()

    # Setup graceful exit on Ctrl+C
    signal.signal(signal.SIGINT, lambda s, f: graceful_exit(s, f, client_socket))

    while True:
        resize_windows(stdscr, chat_win, input_win, status_win)

        status_win.clear()
        status_win.addstr(0, 0, f"Connected as: {CURRENT_USER} | Sound: {'ON' if NOTIFICATION_SOUND else 'OFF'} ", curses.color_pair(4) | curses.A_BOLD)
        status_win.refresh()

        with lock:
            if command_output:
                for line in command_output:
                    messages.append((line, 4))
                command_output.clear()

            redraw_chat(chat_win, messages, scroll_pos)  # Ensure proper redraw before input

        input_win.clear()
        input_win.addstr(0, 0, "❯ ")
        input_win.refresh()
        curses.echo()
        message = input_win.getstr(0, 2, max_x - 3).decode("utf-8").strip()
        curses.noecho()

        if not message:
            continue  # Ignore empty messages

        if message.lower() == "/exit":
            client_socket.send(message.encode("utf-8"))
            break
        elif message.lower() == "/help":
            messages[:] = [msg for msg in messages if not msg[0].startswith(' ')]
            redraw_chat(chat_win, messages, scroll_pos)
            command_output = [
                " /help - Shows this help message.",
                " /exit - Closes the client.",
                " /clear - Clear messages that came from commands",
                " /clearall - Clear all messages",
                " /toggle_sound - Toggle notification sound on/off",
                " /files - Shows all available files from the server",
                " /download (filename) - Download a file from the server",
                " /upload (directory to file) - Upload a file to the server"
            ]
        elif message.lower() == "/toggle_sound":
            messages[:] = [msg for msg in messages if not msg[0].startswith(' ')]
            redraw_chat(chat_win, messages, scroll_pos)
            NOTIFICATION_SOUND = not NOTIFICATION_SOUND
            save_sound_setting(NOTIFICATION_SOUND)
            command_output.append(f" Notification sound {'enabled' if NOTIFICATION_SOUND else 'disabled'}.")
        elif message.lower() == "/clear":
            with lock:
                messages[:] = [msg for msg in messages if not msg[0].startswith(' ')]
                redraw_chat(chat_win, messages, scroll_pos)
        elif message.lower() == "/clearall":
            with lock:
                messages.clear()
                redraw_chat(chat_win, messages, scroll_pos)
        else:
            # Only append if the message doesn't start with '/'
            if not message.startswith("/"):
                if 0 < len(message.strip()) <= MAX_LENGHT:
                    with lock:
                        current_time = datetime.datetime.now().strftime("%X")
                        messages.append((f"{current_time} [{CURRENT_USER}]: {message}", 1))
                        if scroll_pos == 0:
                            redraw_chat(chat_win, messages, scroll_pos)
                client_socket.send(f"{message}".encode("utf-8"))

            # Send the message, even if it starts with "/"
            if message.startswith("/"):
                messages[:] = [msg for msg in messages if not msg[0].startswith(' ')]
                redraw_chat(chat_win, messages, scroll_pos)
                client_socket.send(f"{message}".encode("utf-8"))

        # Sleep to control the refresh rate
        time.sleep(0.1)

    client_socket.close()

if __name__ == "__main__":
    curses.wrapper(client)
