import socket
import customtkinter as ctk
from tkinter import messagebox
import datetime
import threading
import re
import sys
import os
import json
import playsound

# Setting files
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

# Set dark mode theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Global variables for socket connection
client_socket = None
username = None
current_time = datetime.datetime.now().strftime("%X")

def login():
    global client_socket, username

    server_ip = ip_entry.get()
    server_port = int(port_entry.get())
    server_password = password_entry.get()
    username = username_entry.get()
    user_password = user_password_entry.get()

    if not all([server_ip, server_port, server_password, username, user_password]):
        messagebox.showerror("Error", "Please fill in all fields.")
        return

    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((server_ip, server_port))

        client_socket.send(server_password.encode("utf-8"))
        response = client_socket.recv(1024).decode("utf-8")

        if response == "Incorrect server password":
            messagebox.showerror("Error", "Incorrect server password.")
            client_socket.close()
            return

        client_socket.send(username.encode("utf-8"))
        response = client_socket.recv(1024).decode("utf-8")

        if response == "Username rejected or does not exist.":
            messagebox.showerror("Error", "Username does not exist.")
            client_socket.close()
            return

        client_socket.send(user_password.encode("utf-8"))
        response = client_socket.recv(1024).decode("utf-8")

        if response == "Incorrect password.":
            messagebox.showerror("Error", "Incorrect password.")
            client_socket.close()
            return

        login_window.withdraw()
        open_chat_window()
        threading.Thread(target=receive_messages, daemon=True).start()
    except Exception as e:
        messagebox.showerror("Connection Error", f"An error occurred: {e}")

def open_chat_window():
    global chat_window, message_box, message_entry, send_button

    chat_window = ctk.CTkToplevel(root)
    chat_window.title("PyChatGUI")
    chat_window.geometry("500x400")

    message_box = ctk.CTkTextbox(chat_window, height=250, width=480, state=ctk.DISABLED, wrap="word")
    message_box.pack(padx=10, pady=10, fill=ctk.BOTH, expand=True)

    message_box.tag_config("incoming", foreground="DeepSkyBlue2")
    message_box.tag_config("outgoing", foreground="SlateBlue2")
    message_box.tag_config("error", foreground="red")
    message_box.tag_config("client_command_output", foreground="SeaGreen2")

    message_entry = ctk.CTkEntry(chat_window, width=380)
    message_entry.pack(padx=10, pady=5, side=ctk.LEFT, fill=ctk.X, expand=True)

    message_entry.bind("<Return>", lambda event: send_message())

    send_button = ctk.CTkButton(chat_window, text="Send", command=send_message)
    send_button.pack(pady=5, side=ctk.RIGHT, padx=10)

def send_message():
    message = message_entry.get()
    if message:
        if message.startswith("/exit"):
            client_socket.send("/exit".encode("utf-8"))
            message_box.configure(state=ctk.NORMAL)
            message_box.insert(ctk.END, "Exiting client...\n", "outgoing")
            message_box.configure(state=ctk.DISABLED)
            client_socket.close()
            sys.exit()
        elif message.startswith("/help"):
            show_help()
        elif message.startswith("/toggle_sound"):
            toggle_sound()
        else:
            client_socket.send(message.encode("utf-8"))
            if not message.startswith("/"):  # Only display messages that are not commands
                display_message(f"{current_time} [{username}]: {message}\n", "outgoing")

        message_entry.delete(0, ctk.END)  # Clear input field after sending

def receive_messages():
    global client_socket
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                handle_disconnection()
                break
            cleaned_message = process_ansi_colors(message)
            display_message(f"{cleaned_message}\n", "incoming")
            if NOTIFICATION_SOUND:  # Check if sound notifications are enabled
                play_notification_sound()  # Play sound in a separate thread
        except (ConnectionResetError, BrokenPipeError):
            handle_disconnection()
            break
        except Exception as e:
            print(f"Error receiving message: {e}")
            break

def play_notification_sound():
    def play_sound():
        sound_file = "notification.wav"  # Replace with the actual sound file path
        if os.path.exists(sound_file):
            playsound.playsound(sound_file, block=False)
        else:
            print("Notification sound file not found.")

    threading.Thread(target=play_sound, daemon=True).start()

def handle_disconnection():
    display_message("\nConnection lost.\n", "error")
    display_message("Press ENTER to log back in.\n", "client_command_output")
    message_entry.bind("<Return>", lambda event: reconnect())

def reconnect():
    chat_window.destroy()
    root.deiconify()

def display_message(message, tag):
    message_box.configure(state=ctk.NORMAL)
    message_box.insert(ctk.END, f"{message}", tag)
    message_box.configure(state=ctk.DISABLED)
    message_box.yview(ctk.END)

def process_ansi_colors(message):
    ansi_pattern = r"\033\[[0-9;]*m"
    return re.sub(ansi_pattern, "", message)

def show_help():
    help_message = (
        " /help - Shows this help message.\n"
        " /exit - Closes the client.\n"
        " /toggle_sound - Toggle notification sound on/off.\n"
    )
    display_message(help_message, "client_command_output")

def toggle_sound():
    global NOTIFICATION_SOUND
    NOTIFICATION_SOUND = not NOTIFICATION_SOUND
    save_sound_setting(NOTIFICATION_SOUND)
    status = "enabled" if NOTIFICATION_SOUND else "disabled"
    display_message(f" Notification sound {status}.\n", "client_command_output")

# Create login GUI
root = ctk.CTk()
root.title("PyChatGUI Login")
root.geometry("350x400")

ctk.CTkLabel(root, text="Server IP").pack(pady=5)
ip_entry = ctk.CTkEntry(root)
ip_entry.pack(pady=1)

ctk.CTkLabel(root, text="Server Port").pack(pady=5)
port_entry = ctk.CTkEntry(root)
port_entry.pack(pady=1)

ctk.CTkLabel(root, text="Server Password").pack(pady=5)
password_entry = ctk.CTkEntry(root, show="*")
password_entry.pack(pady=1)

ctk.CTkLabel(root, text="Username").pack(pady=5)
username_entry = ctk.CTkEntry(root)
username_entry.pack(pady=1)

ctk.CTkLabel(root, text="User Password").pack(pady=5)
user_password_entry = ctk.CTkEntry(root, show="*")
user_password_entry.pack(pady=1)

login_button = ctk.CTkButton(root, text="Login", command=login)
login_button.pack(pady=20)

login_window = root
root.mainloop()
