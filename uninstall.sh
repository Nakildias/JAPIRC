#!/bin/bash

# Check if JAPIRC is installed
if command -v JAPIRC &> /dev/null; then
  echo "Uninstalling JAPIRC"
  rm -rf ~/.python3/JAPIRC
  sudo rm /bin/JAPIRC
  sudo rm /bin/japirc
  sudo rm /bin/japi
else
echo "Command "JAPIRC" doesn't exist..."
fi

# Check if JAPIRC command is available
if command -v JAPIRC &> /dev/null; then
  echo "Installation was unsuccessful!"
else
  echo "Uninstallation was successful!"
fi
