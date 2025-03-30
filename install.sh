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
if [ ! -d "~/.python3/JAPIRC" ]; then
  echo "Making a directory for python3 location = venv ~/.python3/JAPIRC"
  mkdir -p ~/.python3/JAPIRC
  python3 -m venv ~/.python3/JAPIRC
  cp ./notification.wav ~/.python3/JAPIRC/
  cp ./JAPIRC_TUI.client.py ~/.python3/JAPIRC/
  cp ./JAPIRC_GUI.client.py ~/.python3/JAPIRC/
  cp ./JAPIRC_CLI.server.py ~/.python3/JAPIRC/
  sudo cp ./JAPIRC /bin/
  sudo cp /bin/JAPIRC /bin/japirc
  sudo cp ./JAPIRC /bin/japi
  sudo chmod +x /bin/JAPIRC
  sudo chmod +x /bin/japi
  sudo chmod +x /bin/japirc
  source ~/.python3/JAPIRC/bin/activate
  cd ~/.python3/JAPIRC/bin/
  python3 -m pip install --upgrade pip
  python3 -m pip install --upgrade setuptools wheel
  python3 -m pip install playsound
  python3 -m pip install colored
  python3 -m pip install customtkinter
fi

# Check if JAPIRC command is available
if command -v JAPIRC &> /dev/null; then
  echo "Installation was successful!"
  echo "You may now use the command '"JAPIRC", "japirc" or "japi"'."
else
  echo "Installation was unsuccessful..."
fi
