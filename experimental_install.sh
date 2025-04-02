#!/usr/bin/bash

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
SOURCE_FILES=(                           # Files to copy relative to script location
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

# --- System Dependency Installation (Always Run) ---

info "Attempting to install/update system dependencies (Python 3, TK, venv)..."
PACKAGE_MANAGER=""
INSTALL_CMD_ARGS=() # Use array for safer command construction

if command_exists apt; then
    PACKAGE_MANAGER="apt"
    run_sudo apt update # Update package list first
    # Use array assignment
    INSTALL_CMD_ARGS=(install -y python3 python3-tk python3-venv)
elif command_exists dnf; then
    PACKAGE_MANAGER="dnf"
    INSTALL_CMD_ARGS=(install -y python3 python3-tkinter python3-virtualenv)
elif command_exists pacman; then
    PACKAGE_MANAGER="pacman"
    # -Syy forces refresh even if up-to-date, -S is usually sufficient
    INSTALL_CMD_ARGS=(-S --noconfirm python tk)
elif command_exists emerge; then
    PACKAGE_MANAGER="emerge"
    warn "Gentoo support: This may take time. Ensure USE flags for tk are enabled for python."
    # Consider removing --sync or making it optional? It can be very slow.
    # Maybe ask user? For now, keeping it simple. Using --ask is safer than a -y equivalent.
    INSTALL_CMD_ARGS=(--ask dev-lang/python dev-tk/tk) # Use dev-tk/tk for tk
else
    error "Could not detect a supported package manager (apt, dnf, pacman, emerge). Please install Python 3, Tkinter, and the Python venv module manually."
fi

info "Using ${PACKAGE_MANAGER} to install dependencies."
# Pass arguments as separate strings using the array
run_sudo "${PACKAGE_MANAGER}" "${INSTALL_CMD_ARGS[@]}" || error "Failed to install system dependencies using ${PACKAGE_MANAGER}."
info "System dependency check/installation complete."

# Double check python3 and venv module after attempting install
if ! command_exists python3; then
    error "Python 3 installation failed or python3 is not in PATH."
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
    error "Python 3 'venv' module installation failed or is not available."
fi
info "Python 3 and venv module confirmed."


# --- Cleanup Previous Installation (if exists) ---

if [[ -d "${VENV_DIR}" ]]; then
    info "Existing installation found at ${VENV_DIR}. Reinstalling..."
    info "Removing old virtual environment..."
    rm -rf "${VENV_DIR}" || error "Failed to remove old virtual environment: ${VENV_DIR}"

    info "Removing old executable and links from ${TARGET_BIN_DIR}..."
    run_sudo rm -f "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || warn "Could not remove old executable (might not exist)."
    for link_name in "${LINK_NAMES[@]}"; do
        TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
        run_sudo rm -f "${TARGET_LINK}" || warn "Could not remove old symlink ${link_name} (might not exist)."
    done
    info "Previous installation cleanup complete."
else
    info "No previous installation found at ${VENV_DIR}. Proceeding with new installation."
fi

# --- Virtual Environment Setup & Application Installation (Always Run) ---

info "Creating Python virtual environment in ${VENV_DIR}"
mkdir -p "$(dirname "${VENV_DIR}")" || error "Failed to create parent directory for ${VENV_DIR}"
python3 -m venv "${VENV_DIR}" || error "Failed to create virtual environment."

info "Activating virtual environment for dependency installation (temporary)"
# Activate venv for pip commands - use source for bash compatibility
source "${VENV_DIR}/bin/activate" || error "Failed to activate virtual environment."

info "Upgrading pip..."
python -m pip install --upgrade pip || error "Failed to upgrade pip in venv."
# Make sure those are upgraded or playsound might fail to install.
pip install --upgrade setuptools wheel

info "Installing Python dependencies into virtual environment..."
python -m pip install "${PYTHON_DEPS[@]}" || error "Failed to install Python dependencies."

info "Deactivating virtual environment"
deactivate # Good practice to deactivate after use in script

info "Copying application files into virtual environment..."
# Copy all source files EXCEPT the main executable itself into the venv
for file in "${SOURCE_FILES[@]}"; do
    if [[ "$(basename "${file}")" != "${MAIN_EXECUTABLE_NAME}" ]]; then
        cp "${SCRIPT_DIR}/${file}" "${VENV_DIR}/" || error "Failed to copy ${file} into venv"
    fi
done

info "Installing main executable to ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
run_sudo cp "${SCRIPT_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to copy executable."
run_sudo chmod +x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" || error "Failed to set executable permission."

# Create symlinks (remove first to ensure correctness)
for link_name in "${LINK_NAMES[@]}"; do
    TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
    info "Creating symlink: ${TARGET_LINK} -> ${MAIN_EXECUTABLE_NAME}"
    # Remove existing link first (handles cases where it points elsewhere or is broken)
    run_sudo rm -f "${TARGET_LINK}" || warn "Could not remove potentially existing symlink ${TARGET_LINK}"
    run_sudo ln -s "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}"
done

info "Installation steps completed."


# --- Final Check ---

# Check if the main executable file exists and is executable
if [[ -x "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" ]]; then
    # Check if the command is found in the PATH
    if command_exists "${MAIN_EXECUTABLE_NAME}"; then
        info "-------------------------------------------"
        info " Installation successful!"
        info " Virtual Environment: ${VENV_DIR}"
        info " Executable: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
        info " You should now be able to run the application using: ${MAIN_EXECUTABLE_NAME}, ${LINK_NAMES[*]}"
        info " If the command isn't found immediately, try opening a new terminal session."
        info "-------------------------------------------"
    else
        warn "-------------------------------------------"
        warn " Installation seems complete, but '${MAIN_EXECUTABLE_NAME}' not found in current PATH."
        warn " Executable is located at: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
        warn " Please ensure '${TARGET_BIN_DIR}' is in your PATH environment variable."
        warn " You might need to restart your shell, log out and back in, or manually add it."
        warn " Example (add to ~/.bashrc or ~/.zshrc): export PATH=\"${TARGET_BIN_DIR}:\$PATH\""
        warn "-------------------------------------------"
    fi
else
    error "Installation failed. Could not find executable file at '${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}' or it lacks execute permissions."
fi

exit 0
