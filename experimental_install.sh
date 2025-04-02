#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -e
# Treat unset variables as an error when substituting.
set -u
# Pipelines return the exit status of the last command that failed, or zero if all succeeded.
set -o pipefail

# --- Configuration ---
APP_NAME="JAPIRC"
VENV_DIR="$HOME/.local/share/${APP_NAME}" # More standard location than ~/.python3
TARGET_BIN_DIR="/usr/local/bin"          # Standard location for user-installed executables
SOURCE_FILES=(                            # Files to copy relative to script location
    "notification.wav"
    "JAPIRC_TUI.client.py"
    "JAPIRC_GUI.client.py"
    "JAPIRC_CLI.server.py"
    "JAPIRC" # The main executable script
)
PYTHON_DEPS=( # Python packages to install via pip
    "pip" # Ensure pip is up-to-date first
    "setuptools"
    "wheel"
    "playsound"
    "colored"
    "customtkinter"
    "tkinterdnd2"
)
MAIN_EXECUTABLE_NAME="JAPIRC" # Name of the script to link in TARGET_BIN_DIR
LINK_NAMES=( "japirc" "japi" ) # Additional names (symlinks)

# --- Helper Functions ---
info() {
    echo "[INFO] $1"
}

warn() {
    echo "[WARN] $1" >&2
}

error() {
    echo "[ERROR] $1" >&2
    exit 1
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to run command with sudo, prompting if needed
run_sudo() {
    if [[ $EUID -eq 0 ]]; then
        "$@" # Already root, just run it
    elif command_exists sudo; then
        info "Requesting sudo privileges for: $*"
        sudo "$@"
    else
        error "sudo command not found. Cannot perform required action: $*"
    fi
}

# --- Pre-flight Checks ---

# Check if running as root - inform user sudo will be requested as needed.
if [ "$EUID" -eq 0 ]; then
  warn "Running as root. While not recommended, the script will proceed."
  warn "Consider running as a regular user; sudo will be requested when needed."
fi

# Determine the directory where the script and source files are located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
info "Script source directory: ${SCRIPT_DIR}"

# Check if source files exist
for file in "${SOURCE_FILES[@]}"; do
    if [[ ! -f "${SCRIPT_DIR}/${file}" ]]; then
        error "Required source file not found: ${SCRIPT_DIR}/${file}"
    fi
done

# --- Dependency Installation (Python + TK) ---

if ! command_exists python3; then
    info "Python 3 not found. Attempting installation..."
    PACKAGE_MANAGER=""
    INSTALL_CMD=""

    if command_exists apt; then
        PACKAGE_MANAGER="apt"
        INSTALL_CMD="update && sudo apt install -y python3 python3-tk python3-venv"
    elif command_exists dnf; then
        PACKAGE_MANAGER="dnf"
        INSTALL_CMD="install -y python3 python3-tkinter python3-venv" # Fedora often needs python3-venv explicitly too
    elif command_exists pacman; then
        PACKAGE_MANAGER="pacman"
        INSTALL_CMD="-Sy --noconfirm python tk" # Arch typically bundles venv
    elif command_exists emerge; then
        PACKAGE_MANAGER="emerge"
        # Note: emerge --sync can be very long. Consider if it's always needed.
        # Asking user (--ask) is safer than -y equivalent.
        INSTALL_CMD="--sync && sudo emerge --ask dev-lang/python dev-tk"
        warn "Gentoo support: Ensure USE flags for tk are enabled for python if needed."
    else
        error "Could not detect a supported package manager (apt, dnf, pacman, emerge). Please install Python 3 and Tkinter manually."
    fi

    info "Using ${PACKAGE_MANAGER} to install dependencies."
    run_sudo "${PACKAGE_MANAGER}" ${INSTALL_CMD} || error "Failed to install Python 3 and TK using ${PACKAGE_MANAGER}."
    info "Python 3 and TK installation complete."
else
    info "Python 3 found: $(command -v python3)"
    # Still check for venv module availability
    if ! python3 -m venv --help >/dev/null 2>&1; then
         warn "Python 3 'venv' module not found. Attempting to install..."
         # Add logic similar to above to install *just* the venv package if needed
         if command_exists apt; then
            run_sudo apt update && run_sudo apt install -y python3-venv || error "Failed to install python3-venv."
         elif command_exists dnf; then
            run_sudo dnf install -y python3-venv || error "Failed to install python3-venv."
         # Pacman/Emerge usually include it with python, less likely to be separate
         else
            warn "Could not automatically install 'venv' module for your system. Please install the appropriate package (e.g., python3-venv)."
         fi
    fi
fi

# --- Virtual Environment Setup ---

if [[ ! -d "${VENV_DIR}" ]]; then
    info "Creating Python virtual environment in ${VENV_DIR}"
    mkdir -p "${VENV_DIR}" || error "Failed to create directory ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}" || error "Failed to create virtual environment."

    info "Copying application files..."
    for file in "${SOURCE_FILES[@]}"; do
        # Don't copy the main executable script itself into the venv, only supporting files/libs
        if [[ "${file}" != "${MAIN_EXECUTABLE_NAME}" ]]; then
            cp "${SCRIPT_DIR}/${file}" "${VENV_DIR}/" || error "Failed to copy ${file}"
        fi
    done

    info "Installing Python dependencies into virtual environment..."
    # Ensure pip is up-to-date first
    "${VENV_DIR}/bin/python" -m pip install --upgrade pip || error "Failed to upgrade pip in venv."
    # Install other dependencies
    "${VENV_DIR}/bin/python" -m pip install "${PYTHON_DEPS[@]}" || error "Failed to install Python dependencies."

    info "Installing main executable to ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
    run_sudo cp "${SCRIPT_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to copy executable."
    run_sudo chmod +x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to set executable permission."

    # Create symlinks
    for link_name in "${LINK_NAMES[@]}"; do
        TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
        info "Creating symlink: ${TARGET_LINK} -> ${MAIN_EXECUTABLE_NAME}"
        # Remove existing link if it exists, before creating new one
        run_sudo rm -f "${TARGET_LINK}"
        run_sudo ln -s "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}"
    done

    info "Virtual environment created and dependencies installed."

else
    info "Virtual environment already exists at ${VENV_DIR}. Checking executable link..."
    # Optional: Add logic here to update if needed (re-copy files, re-install deps)
    # For now, just ensure the main executable link is okay
    if [[ ! -x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" ]]; then
        warn "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME} not found or not executable. Re-installing link..."
        run_sudo cp "${SCRIPT_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to copy executable."
        run_sudo chmod +x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to set executable permission."
         # Recreate symlinks too
        for link_name in "${LINK_NAMES[@]}"; do
             TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
             info "Recreating symlink: ${TARGET_LINK} -> ${MAIN_EXECUTABLE_NAME}"
             run_sudo rm -f "${TARGET_LINK}"
             run_sudo ln -s "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}"
        done
    fi
    info "Skipping venv creation and dependency installation."
fi


# --- Final Check ---

if command_exists "${MAIN_EXECUTABLE_NAME}"; then
    info "-------------------------------------------"
    info " Installation successful!"
    info " Virtual Environment: ${VENV_DIR}"
    info " Executable: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
    info " You can now run the application using: ${MAIN_EXECUTABLE_NAME}, ${LINK_NAMES[*]}"
    info "-------------------------------------------"
else
    # This check might fail if /usr/local/bin isn't immediately in PATH for the current shell
    # Double-check the file exists as a fallback
    if [[ -x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" ]]; then
        warn "Installation seems complete, but '${MAIN_EXECUTABLE_NAME}' not found in PATH."
        warn "Please ensure '${TARGET_BIN_DIR}' is in your PATH environment variable."
        warn "You might need to restart your shell or log out and back in."
        info "Executable is located at: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
    else
        error "Installation failed. Could not find executable command '${MAIN_EXECUTABLE_NAME}'."
    fi
fi

exit 0
