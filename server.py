import socket
import threading
import json
import hashlib
import datetime
import time
from colored import fg, attr

# Server Configuration
HOST = "0.0.0.0"
PORT = 5050
USER_CREDENTIALS_FILE = "user_credentials.json"
SERVER_PASSWORD = "SuperSecret"  # Change this to your desired server password
SERVER_NAME = "Server Name"  # Change this to your desired server name
current_time = datetime.datetime.now().strftime("%X")

def color_text(text, color):
    return f"{fg(color)}{text}{attr('reset')}"

# Load or Create User Credentials
def load_credentials():
    try:
        with open(USER_CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_credentials(credentials):
    with open(USER_CREDENTIALS_FILE, "w") as f:
        json.dump(credentials, f)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

user_credentials = load_credentials()
clients = {}

def handle_client(client_socket, username):
#    client_socket.send(f"Welcome to {SERVER_NAME}!".encode())
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                break
            if message.lower() == "/exit":
                client_socket.send(color_text("Goodbye!\n", "red").encode("utf-8"))
                break
            elif message.lower() == "/help":
                client_socket.send(b"Commands:\n/msg <message> - Send a message\n/exit - Leave the chat\n")
            elif message.startswith("msg "):
                msg_content = message[4:]
                if len(msg_content) < 1:
                    client_socket.send(b"Error: Message must be at least 1 character long.\n")
                elif len(msg_content) > 150:
                    client_socket.send(b"Error: Message cannot exceed 150 characters.\n")
                else:
                    formatted_msg = f"{current_time} [{color_text(username, 'cyan')}]: {msg_content}"
                    print(formatted_msg)
                    broadcast(formatted_msg, client_socket)
            else:
                client_socket.send(b"Unknown command. Type /help for commands.\n")
        except:
            break
    print(color_text(f"{username} disconnected.", "red"))
    client_socket.close()
    del clients[client_socket]
    broadcast(color_text(f"{username} has left the chat.\n", "yellow"), None)

def broadcast(message, sender_socket):
    for client in list(clients.keys()):
        if client != sender_socket:
            try:
                client.send(message.encode("utf-8"))
            except:
                client.close()
                del clients[client]

def handle_login(client_socket, addr):
    client_socket.send(b"Enter server password: ")
    server_password = client_socket.recv(1024).decode("utf-8").strip()
    if server_password != SERVER_PASSWORD:
        client_socket.send(color_text("Incorrect server password! Connection closed.\n", "red").encode("utf-8"))
        client_socket.close()
        return

    client_socket.send(b"Enter your username: ")
    try:
        client_socket.settimeout(60)
        username = client_socket.recv(1024).decode("utf-8").strip()

        # Check for maximum length and spaces
        if len(username) > 18:
            client_socket.send(color_text("Maximum Length Exceeded (18 Characters)\n", "red").encode("utf-8"))
            client_socket.close()
            return
        if " " in username:
            client_socket.send(color_text("No Spaces Allowed in Usernames\n", "red").encode("utf-8"))
            client_socket.close()
            return

        # Check if the username is already in use
        if username in clients.values():
            client_socket.send(color_text("It seems you are already connected to this server!\n", "red").encode("utf-8"))
            client_socket.close()
            return

        client_socket.send(b"Enter your password: ")
        password = client_socket.recv(1024).decode("utf-8").strip()
        client_socket.settimeout(None)
    except socket.timeout:
        client_socket.send(color_text("Login timeout! Connection closed.\n", "red").encode("utf-8"))
        client_socket.close()
        return

    hashed_password = hash_password(password)

    if username in user_credentials:
        if user_credentials[username] != hashed_password:
            client_socket.send(color_text("Incorrect password! Connection closed.\n", "red").encode("utf-8"))
            client_socket.close()
            return
    else:
        user_credentials[username] = hashed_password
        save_credentials(user_credentials)

    clients[client_socket] = username
    print(color_text(f"{username} joined from {addr}", "cyan"))
    broadcast(color_text(f"{username} has joined the chat!\n", "green"), None)

    client_thread = threading.Thread(target=handle_client, args=(client_socket, username))
    client_thread.start()


def server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(color_text(f"Server started on {HOST}:{PORT}", "green"))
    try:
        while True:
            client_socket, addr = server_socket.accept()
            login_thread = threading.Thread(target=handle_login, args=(client_socket, addr))
            login_thread.start()
    except KeyboardInterrupt:
        print(color_text("Server shutting down.", "red"))
    finally:
        for client in list(clients.keys()):
            client.send(color_text("Server shutting down. Connection lost.\n", "red").encode("utf-8"))
            client.close()
        server_socket.close()

if __name__ == "__main__":
    server()
