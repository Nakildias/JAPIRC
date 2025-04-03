# Just Another Python Internet Relay Chat
# Supported linux distros
### Arch Linux and distros based on it (Tested)
### Debian and distros based on it (Tested)
### Fedora and distros based on it (Tested)
# Key features
### Easy installation with bash script
### Chat with friends.
### Share files with friends.
### Drag & Drop file uploading. (GUI Version)
### User registration is togglable is server settings.
### Client & Server side commands.
### Operator role.
### Secured by server password.
### GUI & TUI Client.


# Installation Guide

> Follow the steps below to install and set up JAPIRC on your linux system.
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

Once Git is installed, clone the JAPIRC repository by running the following command:

> git clone https://github.com/Nakildias/JAPIRC

# 3. Navigate to the Project Directory

Change into the newly created JAPIRC directory:

> cd JAPIRC

# 4. Install JAPIRC

Inside the JAPIRC directory, run the installation script:

> bash ./install.sh

# 5. Enter Your Sudo Password

> The script will prompt you for your sudo password. Enter it to proceed with the installation.

# 6. Run JAPIRC with either of those 3 commands:

> JAPIRC
> japirc
> japi

# 7. Configuration (Recommended)

> By default, JAPIRC runs on port 5050 and uses the password "SuperSecret" for the server.

If you’d like to change the default settings (port or password), you can edit the "JAPIRC_CLI.server.py" file located at:

> ~/.local/share/JAPIRC/JAPIRC_CLI.server.py

Use any text editor of your choice to modify these values sudo/root not required.

  
