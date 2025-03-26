#!/bin/bash

# Check if the script is being run with sudo
if [ "$EUID" -eq 0 ]; then
  echo "This script cannot be run with sudo. Please run it as a normal user."
  exit 1
fi

# UNTESTED FOR MOST DISTROS WILL BE TESTED WITHIN A COUPLE OF DAYS.
  # If apt is available (Debian/Ubuntu)
  if command -v apt &> /dev/null; then
    sudo apt update && sudo apt install python3 python3-pip python3.12-venv
  fi

if [ -z "$(command -v python3)" ]; then
  echo "Python 3 is not installed..."
  echo "Installing python3 package for your distro...."

  # If pacman is available (Arch/Manjaro)
  if command -v pacman &> /dev/null; then
    sudo pacman -Sy python
  fi



  # If dnf is available (Fedora)
  if command -v dnf &> /dev/null; then
    sudo dnf install python3
  fi

  # If emerge is available (Gentoo)
  if command -v emerge &> /dev/null; then
    sudo emerge --sync && sudo emerge --ask dev-lang/python
  fi
else
  echo "Python 3 is installed, skipping installation."
fi

# Check if the directory for the Python virtual environment exists
if [ ! -d "~/.python3/PyChatCLI" ]; then
  echo "Making a directory for python3 location = venv ~/.python3/PyChatCLI"
  mkdir -p ~/.python3/PyChatCLI
  python3 -m venv ~/.python3/PyChatCLI
  cp ./notification.wav ~/.python3/PyChatCLI/
  cp ./client.py ~/.python3/PyChatCLI/
  cp ./server.py ~/.python3/PyChatCLI/
  sudo cp ./PyChatCLI /bin/
  sudo chmod +x /bin/PyChatCLI
  source ~/.python3/PyChatCLI/bin/activate
  cd ~/.python3/PyChatCLI/bin/
  python3 -m pip install --upgrade pip
  python3 -m pip install --upgrade setuptools wheel
  python3 -m pip install playsound
  python3 -m pip install colored
fi

# Check if PyChatCLI command is available
if command -v PyChatCLI &> /dev/null; then
  echo "Installation was successful!"
  echo "You may now use the command 'PyChatCLI'."
else
  echo "Installation was unsuccessful..."
fi
