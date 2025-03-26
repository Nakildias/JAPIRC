# Installation Guide

### Follow the steps below to install and set up PyChatCLI on your linux system.
# 1. Install Git

Debian Based:

> sudo apt-get install git

Fedora Based:

> sudo dnf install git

Arch Linux Based:

> sudo pacman -S git

Gentoo Based:

> sudo emerge dev-vcs/git

# 2. Clone the Repository

Once Git is installed, clone the PyChatCLI repository by running the following command:

> git clone https://github.com/Nakildias/PyChatCLI

# 3. Navigate to the Project Directory

Change into the newly created PyChatCLI directory:

> cd PyChatCLI

# 4. Install PyChatCLI

Inside the PyChatCLI directory, run the installation script:

> bash ./install.sh

# 5. Enter Your Sudo Password

> The script will prompt you for your sudo password. Enter it to proceed with the installation.

# 6. Run PyChatCLI

> PyChatCLI

# 7. Configuration (Recommended)

> By default, PyChatCLI runs on port 5050 and uses the password "SuperSecret" for the server.

If you’d like to change the default settings (port or password), you can edit the server.py file located at:

> ~/.python3/PyChatCLI/server.py

Use any text editor of your choice to modify these values sudo/root not required.

#  Features 

###  Username & Password: Users can log in using their own usernames and passwords to access the chat server.
###  Server Password: The chat server administrator can set a password that users must enter before they can join the chat.
###  Ping sounds: When a new message comes up you will hear it thanks to the playsound library https://pypi.org/project/playsound/
  
