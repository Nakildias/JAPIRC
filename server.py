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
OPS_FILE = "ops.json"  # File to store operators
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

def load_ops():
    try:
        with open(OPS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_ops(ops):
    with open(OPS_FILE, "w") as f:
        json.dump(ops, f)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

user_credentials = load_credentials()
ops = load_ops()
clients = {}

def handle_client(client_socket, username):
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                break
            msg_content = message.strip()

            # Command handling based on op status
            if msg_content.startswith("/kick ") or msg_content.startswith("/stop") or msg_content.startswith("/restart") or msg_content.startswith("/list" ):
                # Ensure user is an operator
                if username not in ops:
                    client_socket.send(color_text("You do not have permission to execute this command.\n", "red").encode("utf-8"))
                    continue  # Skip normal message processing if it's a restricted command

                # Handle the command if it's valid (forward to command handler function)
                handle_server_command(client_socket, username, msg_content)
                continue  # Skip the normal message handling to avoid broadcast

            # If it's not a command, handle it as a normal chat message
            if len(msg_content) < 1:
                client_socket.send(b"Error: Message must be at least 1 character long.\n")
            elif len(msg_content) > 150:
                print(f"{username} sent a message that is too long: {len(msg_content)}")
                client_socket.send(b"Error: Message cannot exceed 150 characters.\n")
            elif msg_content.startswith("/"):
                continue
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
    broadcast(color_text(f"{current_time} {username} has left the chat.\n", "yellow"), None)

def handle_server_command(client_socket, username, message):
    if message.startswith("/kick "):
        parts = message.split(" ", 2)
        if len(parts) < 3:
            client_socket.send(color_text("Usage: /kick <username> <reason>\n", "red").encode("utf-8"))
            return
        target_user, reason = parts[1], parts[2]
        # Implement the kicking logic here
        for client, user in list(clients.items()):
            if user == target_user:
                client.send(color_text(f"{current_time} You have been kicked: {reason}\n", "red").encode("utf-8"))
                client.shutdown(socket.SHUT_RDWR)  # Shutdown both reading and writing
                client.close()  # Now close the socket
                del clients[client]
                broadcast(color_text(f"{current_time} {target_user} was kicked: {reason}\n", "yellow"), None)
                print(color_text(f"{current_time} Kicked {target_user}: {reason}", "red"))
                return
        client_socket.send(color_text("User not found.\n", "red").encode("utf-8"))

    elif message == "/stop":
        # Implement the server stop logic here
        print(color_text("Stopping server...", "red"))
        for client in list(clients.keys()):
            client.send(color_text(f"{current_time} Connection lost. Reason: (Server stopped)\n", "red").encode("utf-8"))
            client.shutdown(socket.SHUT_RDWR)
            client.close()
        server_socket.close()  # Properly close the server socket
        os._exit(0)

    elif message == "/restart":
        # Implement the server restart logic here
        print(color_text("Restarting server...", "red"))
        for client in list(clients.keys()):
            client.send(color_text(f"{current_time} Connection lost. Reason: (Server is restarting...)\n", "red").encode("utf-8"))
            client.shutdown(socket.SHUT_RDWR)
            client.close()
        server_socket.close()  # Properly close the server socket
        os.execv(sys.executable, [sys.executable] + sys.argv)  # Start the server back up

    elif message == "/list":
        # Implement the server list logic here
            client_socket.send(color_text(f" Connected Users:", "red").encode("utf-8"))
            for user in clients.values():
                client_socket.send(color_text(f" [{user}] ", "red").encode("utf-8"))

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
        client_socket.send(color_text("Connection lost. Reason: (Wrong Password)\n", "red").encode("utf-8"))
        client_socket.close()
        return

    client_socket.send(b"Enter your username: ")
    try:
        client_socket.settimeout(60)
        username = client_socket.recv(1024).decode("utf-8").strip()

        if len(username) > 18:
            client_socket.send(color_text("Connection lost. Reason: (Username is over 18 characters)\n", "red").encode("utf-8"))
            client_socket.close()
            return
        if " " in username:
            client_socket.send(color_text("Connection lost. Reason: (No spaces allowed in usernames)\n", "red").encode("utf-8"))
            client_socket.close()
            return
        if username in clients.values():
            client_socket.send(color_text("Connection lost. Reason: (You are already connected)\n", "red").encode("utf-8"))
            client_socket.close()
            return

        client_socket.send(b"Enter your password: ")
        password = client_socket.recv(1024).decode("utf-8").strip()
        client_socket.settimeout(None)
    except socket.timeout:
        client_socket.send(color_text("Connection lost. Reason: (Login Timeout)\n", "red").encode("utf-8"))
        client_socket.close()
        return

    hashed_password = hash_password(password)

    if username in user_credentials:
        if user_credentials[username] != hashed_password:
            client_socket.send(color_text("Connection lost. Reason: (Wrong Password)\n", "red").encode("utf-8"))
            client_socket.close()
            return
    else:
        user_credentials[username] = hashed_password
        save_credentials(user_credentials)

    clients[client_socket] = username
    print(color_text(f"{current_time} {username} joined from {addr}", "cyan"))
    broadcast(color_text(f"{current_time} {username} has joined the chat!\n", "green"), None)

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
                    client.send(color_text(f"{current_time} You have been kicked: {reason}\n", "red").encode("utf-8"))
                    client.shutdown(socket.SHUT_RDWR)  # Shutdown both reading and writing
                    client.close()  # Now close the socket
                    del clients[client]
                    broadcast(color_text(f"{current_time} {username} was kicked: {reason}\n", "yellow"), None)
                    print(f"{current_time} Kicked {username}: {reason}")
                    break
            else:
                print(color_text("User not found or not online", "red"))
        elif command.startswith("/msg "):
            message = command[5:]
            broadcast(color_text(f"{current_time} [Server]: {message}\n", "green"), None)
            print(f"{current_time} [Server]: {message}")
        elif command == "/list":
            print("Connected Users:")
            for user in clients.values():
                print(f"- {user}")
        elif command == "/stop":
            print(color_text("Stopping server...", "red"))
            for client in list(clients.keys()):
                client.send(color_text("Connection lost. Reason: (Server stopped)\n", "red").encode("utf-8"))
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            server_socket.close()  # Properly close the server socket
            os._exit(0)
        elif command == "/restart":
            print(color_text(f"{current_time}Restarting server...", "red"))
            for client in list(clients.keys()):
                client.send(color_text(f"{current_time}Connection lost. Reason: (Server is restarting...)\n", "red").encode("utf-8"))
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            server_socket.close()  # Properly close the server socket
            os.execv(sys.executable, [sys.executable] + sys.argv)  # Start the server back up
        elif command.startswith("/op "):
            parts = command.split(" ", 1)  # Split only into two parts: command and username
            if len(parts) < 2 or not parts[1].strip():
                print("Usage: /op <username>")
                continue
            username = parts[1].strip()
            if username not in user_credentials:
                print(f"User {username} does not exist.")
                continue
            if username in ops:
                print(f"{username} is already an operator.")
            else:
                ops.append(username)
                save_ops(ops)
                print(f"{current_time} {username} is now an operator.")
        elif command.startswith("/deop "):
            parts = command.split(" ", 1)  # Split only into two parts: command and username
            if len(parts) < 2 or not parts[1].strip():
                print("Usage: /deop <username>")
                continue
            username = parts[1].strip()
            if username not in ops:
                print(f"{username} is not an operator.")
            else:
                ops.remove(username)
                save_ops(ops)
                print(f"{current_time} {username} is no longer an operator.")
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
            print("/op <username> - Make a user an operator.")
            print("")
            print("/deop <username> - Remove a user from the operator list.")
            print("")
        else:
            print("Unknown command.")

def server():
    global server_socket  # Make server_socket accessible globally
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(color_text(f"{current_time} Server started on {HOST}:{PORT}", "green"))
    threading.Thread(target=console_commands, daemon=True).start()
    try:
        while True:
            client_socket, addr = server_socket.accept()
            login_thread = threading.Thread(target=handle_login, args=(client_socket, addr))
            login_thread.start()
    except KeyboardInterrupt:
        print(color_text(f"{current_time} Stopping server...", "red"))
        for client in list(clients.keys()):
            try:
                client.send(color_text(f"{current_time} Server shutting down. Connection lost.\n", "red").encode("utf-8"))
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except:
                pass
        server_socket.shutdown(socket.SHUT_RDWR)
        server_socket.close()
        os._exit(0)

if __name__ == "__main__":
    server()
