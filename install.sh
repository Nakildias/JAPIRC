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
TARGET_BIN_DIR="/usr/local/bin"           # Standard location for user-installed executables
SOURCE_FILES=(                          # Files to copy relative to script location
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

info "Attempting to install/update system dependencies (Python 3, TK support, venv)..."
PACKAGE_MANAGER=""
NEEDS_TK_SETUP=false # Flag for Gentoo

if command_exists apt; then
    PACKAGE_MANAGER="apt"
    run_sudo apt update # Update package list first
    run_sudo apt install -y python3 python3-tk python3-venv || error "Failed using apt."
elif command_exists dnf; then
    PACKAGE_MANAGER="dnf"
    run_sudo dnf install -y python3 python3-tkinter python3-virtualenv || error "Failed using dnf."
elif command_exists pacman; then
    PACKAGE_MANAGER="pacman"
    run_sudo pacman -S --noconfirm --needed python tk || error "Failed using pacman." # --needed avoids reinstall
elif command_exists emerge; then
    PACKAGE_MANAGER="emerge"
    info "Gentoo detected. Ensuring python and gentoolkit are installed."
    # Ensure python and gentoolkit (for equery) are present first.
    # We don't explicitly emerge tk here; we manage it via Python's USE flag.
    run_sudo emerge --ask --noreplace dev-lang/python app-portage/gentoolkit || error "Failed initial emerge for python/gentoolkit."

    info "Checking if 'tk' USE flag is enabled for dev-lang/python..."
    # Use equery to check the USE flags for python. We need to capture output and handle potential errors.
    # Ensure equery command exists after attempting to emerge gentoolkit
    if ! command_exists equery; then
        error "'equery' command not found. Please ensure app-portage/gentoolkit is installed."
    fi

    # Check if tk flag is explicitly enabled (+) or disabled (-)
    if equery -q uses dev-lang/python | grep -q '\[+\] tk'; then
        info "'tk' USE flag is already enabled for dev-lang/python."
    elif equery -q uses dev-lang/python | grep -q '\[-\] tk'; then
        info "'tk' USE flag is disabled for dev-lang/python. Attempting to enable..."
        NEEDS_TK_SETUP=true
    else
        # This case might mean tk isn't a relevant flag for the installed version,
        # or equery output format changed. Warn but proceed cautiously.
        warn "Could not definitively determine 'tk' USE flag status for dev-lang/python via equery. Proceeding, but Tkinter might not work."
        # We could still *try* to set it, assuming it's just missing from output
        NEEDS_TK_SETUP=true
    fi

    if [[ "$NEEDS_TK_SETUP" == true ]]; then
        PACKAGE_USE_DIR="/etc/portage/package.use"
        PYTHON_USE_FILE="${PACKAGE_USE_DIR}/python_japirc" # Specific file for this app
        PYTHON_USE_LINE="dev-lang/python tk"

        info "Ensuring ${PACKAGE_USE_DIR} directory exists..."
        run_sudo mkdir -p "${PACKAGE_USE_DIR}" || error "Failed to create ${PACKAGE_USE_DIR}"

        info "Checking if '${PYTHON_USE_LINE}' is already in ${PYTHON_USE_FILE} or other .use files..."
        # Use grep across the directory. -q for quiet, -s for no error on non-existent files, -F for fixed string, -x for exact line match
        if run_sudo grep -qsFx "${PYTHON_USE_LINE}" "${PACKAGE_USE_DIR}"/* ; then
            info "'${PYTHON_USE_LINE}' already configured in package.use."
            # Even if configured, Python might not have been emerged with it yet.
            info "Will still check if re-emerge is needed."
        else
            info "Adding '${PYTHON_USE_LINE}' to ${PYTHON_USE_FILE}..."
            # Use tee with sudo to append the line, creating the file if needed.
            echo "${PYTHON_USE_LINE}" | run_sudo tee -a "${PYTHON_USE_FILE}" > /dev/null || error "Failed to add tk USE flag to ${PYTHON_USE_FILE}"
        fi

        warn "The 'tk' USE flag has been configured for dev-lang/python."
        warn "Python needs to be re-emerged to apply this change."
        warn "This script will now run 'emerge --ask --changed-use dev-lang/python'."
        warn "Please review the changes emerge proposes and confirm if they are acceptable."
        # Re-emerge python *only*, applying the new USE flag.
        # --changed-use is preferred, but --newuse might also be needed depending on exact state.
        # --ask is CRITICAL for safety.
        run_sudo emerge --ask --changed-use --deep dev-lang/python || error "Failed to re-emerge python with new USE flags. Tkinter may not work."
        info "dev-lang/python re-emerged successfully with 'tk' USE flag enabled."
    fi

else
    error "Could not detect a supported package manager (apt, dnf, pacman, emerge). Please install Python 3, Tkinter support, and the Python venv module manually."
fi

# No need for INSTALL_CMD_ARGS anymore as installation happens within each block

info "System dependency check/installation complete."

# Double check python3 and venv module after attempting install
if ! command_exists python3; then
    error "Python 3 installation failed or python3 is not in PATH."
fi
# Check for venv module availability
# Redirect stderr to /dev/null to suppress potential module-not-found errors if check fails
if ! python3 -m venv --help >/dev/null 2>&1; then
    error "Python 3 'venv' module installation failed or is not available."
fi
info "Python 3 and venv module confirmed."


# --- Cleanup Previous Installation (if exists) ---
# [ Rest of the script remains the same... ]

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
pip install --upgrade setuptools wheel || error "Failed to upgrade setuptools/wheel." # Added error check

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
    run_sudo ln -sf "${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}" "${TARGET_LINK}" || error "Failed to create symlink ${link_name}" # Added -f to force overwrite if rm failed
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
