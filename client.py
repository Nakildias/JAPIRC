import socket
import threading
import curses
import datetime
import re
from playsound import playsound

MAX_LENGHT = 150

current_user = ""

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
    threading.Thread(target=playsound, args=(sound_file,), daemon=True).start()

def receive_messages(client_socket, messages, lock, chat_win, scroll_pos):
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                break
            message = strip_ansi_codes(message)
            with lock:
                play_sound_in_background('notification.wav') #Credits to AnthonyRox over on freesound
                messages.append((message, 2))
                if scroll_pos == 0:
                    redraw_chat(chat_win, messages, scroll_pos)
        except:
            with lock:
                messages.append(("Connection lost.", 3))
            break

def redraw_chat(chat_win, messages, scroll_pos):
    chat_win.clear()
    max_y, _ = chat_win.getmaxyx()
    start = max(0, len(messages) - max_y + scroll_pos)
    end = start + max_y
    for i, (msg, color) in enumerate(messages[start:end]):
        chat_win.addstr(i, 0, msg, curses.color_pair(color))
    chat_win.refresh()

def resize_windows(stdscr, chat_win, input_win, status_win):
    max_y, max_x = stdscr.getmaxyx()
    chat_win.resize(max_y - 3, max_x)
    input_win.resize(1, max_x)
    status_win.resize(1, max_x)
    chat_win.mvwin(0, 0)
    input_win.mvwin(max_y - 2, 0)
    status_win.mvwin(max_y - 1, 0)

def client(stdscr):
    global current_user

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
    stdscr.refresh()
    server_password = stdscr.getstr().decode("utf-8")
    client_socket.send(server_password.encode("utf-8"))

    stdscr.addstr(3, 0, strip_ansi_codes(client_socket.recv(1024).decode("utf-8")), curses.color_pair(2))
    stdscr.refresh()
    username = stdscr.getstr().decode("utf-8")
    client_socket.send(username.encode("utf-8"))
    current_user = username

    stdscr.refresh()
    stdscr.addstr(4, 0, strip_ansi_codes(client_socket.recv(1024).decode("utf-8")), curses.color_pair(2))
    password = stdscr.getstr().decode("utf-8")
    client_socket.send(password.encode("utf-8"))


    curses.noecho()

    receive_thread = threading.Thread(target=receive_messages, args=(client_socket, messages, lock, chat_win, scroll_pos), daemon=True)
    receive_thread.start()

    while True:
        resize_windows(stdscr, chat_win, input_win, status_win)

        status_win.clear()
        status_win.addstr(0, 0, f"Connected as : {current_user} ", curses.color_pair(4) | curses.A_BOLD)
        status_win.refresh()

        with lock:
            if command_output:
                for line in command_output:
                    messages.append((line, 4))
                command_output.clear()
            redraw_chat(chat_win, messages, scroll_pos)

        input_win.clear()
        input_win.addstr(0, 0, "> ")
        input_win.refresh()
        curses.echo()
        input_win.keypad(False)
        message = input_win.getstr(0, 2, max_x - 3).decode("utf-8")
        curses.noecho()

        if message.lower() == "/exit":
            client_socket.send(message.encode("utf-8"))
            break
        elif message.lower() == "/help":
            command_output = [
                "/exit       - Leave the chat",
                "/clear      - Clear messages that came from commands",
                "/clearall   - Clear all messages"
            ]
        elif message.lower() == "/clear":
            with lock:
                messages[:] = [msg for msg in messages if not msg[0].startswith('/')]
                redraw_chat(chat_win, messages, scroll_pos)
        elif message.lower() == "/clearall":
            with lock:
                messages.clear()
                redraw_chat(chat_win, messages, scroll_pos)
        else:
            if len(message.strip()) > 0 and len(message.strip()) <= MAX_LENGHT:
                with lock:
                    current_time = datetime.datetime.now().strftime("%X")
                    messages.append((f"{current_time} [{current_user}]: {message}", 1))
                    if scroll_pos == 0:
                        redraw_chat(chat_win, messages, scroll_pos)
                client_socket.send(f"msg {message}".encode("utf-8"))

    client_socket.close()

if __name__ == "__main__":
    curses.wrapper(client)
