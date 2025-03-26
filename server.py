import socket
import threading
import json
import hashlib
import datetime
import time
import os #To handle restarting
import sys #To handle restarting
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
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                break
            msg_content = message[4:]

            if len(msg_content) < 1:
                client_socket.send(b"Error: Message must be at least 1 character long.\n")
            elif len(msg_content) > 150:
                print(f"{username} sent a message that is too long: {len(msg_content)}")
                client_socket.send(b"Error: Message cannot exceed 150 characters.\n")
            else:
                formatted_msg = f"{current_time} [{color_text(username, 'cyan')}]: {msg_content}"
                print(formatted_msg)
                broadcast(formatted_msg, client_socket)
        except Exception as e:
            print(f"Error handling client {username}: {e}")
            break

    print(color_text(f"{username} disconnected.", "red"))
    client_socket.close()
    clients.pop(client_socket, None)
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

        if len(username) > 18:
            client_socket.send(color_text("Maximum Length Exceeded (18 Characters)\n", "red").encode("utf-8"))
            client_socket.close()
            return
        if " " in username:
            client_socket.send(color_text("No Spaces Allowed in Usernames\n", "red").encode("utf-8"))
            client_socket.close()
            return
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

def console_commands():
    while True:
        command = input()
        if command.startswith("/kick "):
            parts = command.split(" ", 2)
            if len(parts) < 3:
                print("Usage: /kick <username> <reason>")
                continue
            username, reason = parts[1], parts[2]
            for client, user in list(clients.items()):
                if user == username:
                    client.send(color_text(f"You have been kicked: {reason}\n", "red").encode("utf-8"))
                    client.shutdown(socket.SHUT_RDWR)  # Shutdown both reading and writing
                    client.close()  # Now close the socket
                    del clients[client]
                    broadcast(color_text(f"{username} was kicked: {reason}\n", "yellow"), None)
                    print(f"Kicked {username}: {reason}")
                    break
            else:
                print("User not found.")
        elif command.startswith("/msg "):
            message = command[5:]
            broadcast(color_text(f"[Server]: {message}\n", "green"), None)
            print(f"Message sent: {message}")
        elif command == "/list":
            print("Connected Users:")
            for user in clients.values():
                print(f"- {user}")
        elif command == "/stop":
            print("Stopping server...")
            for client in list(clients.keys()):
                client.send(color_text("Server shutting down. Connection lost.\n", "red").encode("utf-8"))
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            server_socket.close()  # Properly close the server socket
            os._exit(0)
        elif command == "/restart":
            print("Restarting server...")
            for client in list(clients.keys()):
                client.send(color_text("Server is restarting. Connection lost.\n", "yellow").encode("utf-8"))
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            server_socket.close()  # Properly close the server socket
            os.execv(sys.executable, [sys.executable] + sys.argv)  # Start the server back up
        elif command == "/help":
            print("")
            print("/list - List all connected clients")
            print("")
            print("/msg (message) - Send a message to all connected clients.")
            print("")
            print("/kick (username) (reason) - Kick a client from the server.")
            print("")
            print("/stop - Stop the server.")
            print("")
            print("/restart - Restart the server.")
            print("")
        else:
            print("Unknown command.")

def server():
    global server_socket  # Make server_socket accessible globally
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(color_text(f"Server started on {HOST}:{PORT}", "green"))
    threading.Thread(target=console_commands, daemon=True).start()
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
