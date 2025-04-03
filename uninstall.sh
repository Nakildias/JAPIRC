#!/usr/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e
# Treat unset variables as an error when substituting.
set -u
# Pipelines return the exit status of the last command that failed, or zero if all succeeded.
set -o pipefail

# --- Configuration (Must match the install script) ---
APP_NAME="JAPIRC"
VENV_DIR="$HOME/.local/share/${APP_NAME}"
TARGET_BIN_DIR="/usr/local/bin"
MAIN_EXECUTABLE_NAME="JAPIRC" # Name of the main executable in TARGET_BIN_DIR
LINK_NAMES=( "japirc" "japi" ) # Additional names (symlinks)

# Gentoo specific USE flag configuration (if applicable)
PACKAGE_USE_DIR="/etc/portage/package.use"
PYTHON_USE_FILE="${PACKAGE_USE_DIR}/python_japirc" # Specific file created by installer
PYTHON_USE_LINE="dev-lang/python tk"


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
 warn "Sudo will not be explicitly requested as you are already root."
fi

info "Starting uninstallation of ${APP_NAME}..."

# --- Removal Steps ---

# 1. Remove Executable and Symlinks from TARGET_BIN_DIR
TARGET_EXECUTABLE="${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
if [[ -f "${TARGET_EXECUTABLE}" || -L "${TARGET_EXECUTABLE}" ]]; then # Check if file or link exists
    info "Removing executable: ${TARGET_EXECUTABLE}"
    run_sudo rm -f "${TARGET_EXECUTABLE}" || warn "Failed to remove executable ${TARGET_EXECUTABLE}. It might require manual removal."
else
    info "Executable ${TARGET_EXECUTABLE} not found. Skipping removal."
fi

for link_name in "${LINK_NAMES[@]}"; do
    TARGET_LINK="${TARGET_BIN_DIR}/${link_name}"
    # Check specifically if it's a symbolic link before attempting removal
    if [[ -L "${TARGET_LINK}" ]]; then
        info "Removing symlink: ${TARGET_LINK}"
        run_sudo rm -f "${TARGET_LINK}" || warn "Failed to remove symlink ${TARGET_LINK}. It might require manual removal."
    elif [[ -e "${TARGET_LINK}" ]]; then
         warn "Found '${TARGET_LINK}' but it is not a symlink. Skipping removal to avoid deleting unrelated files."
    else
        info "Symlink ${TARGET_LINK} not found. Skipping removal."
    fi
done

# 2. Remove Virtual Environment Directory
if [[ -d "${VENV_DIR}" ]]; then
    info "Removing virtual environment directory: ${VENV_DIR}"
    # Typically doesn't require sudo as it's in $HOME, but check just in case
    if [[ -w "$(dirname "${VENV_DIR}")" ]]; then
         rm -rf "${VENV_DIR}" || error "Failed to remove virtual environment: ${VENV_DIR}. Check permissions."
    else
         warn "Parent directory of ${VENV_DIR} might not be writable by current user. Attempting with sudo..."
         # It's unusual for VENV_DIR *itself* to need sudo if created correctly, but parent dir might
         run_sudo rm -rf "${VENV_DIR}" || error "Failed to remove virtual environment using sudo: ${VENV_DIR}. Check permissions or remove manually."
    fi
else
    info "Virtual environment directory ${VENV_DIR} not found. Skipping removal."
fi

# 3. Remove Gentoo USE flag configuration (if applicable and exists)
# Check if the specific config file created by the installer exists
if [[ -f "${PYTHON_USE_FILE}" ]]; then
    info "Found Gentoo USE flag configuration file: ${PYTHON_USE_FILE}"
    # Check if the specific line exists in the file
    # Use grep -q for quiet check, -F for fixed string, -x for exact line match
    if run_sudo grep -qsFx "${PYTHON_USE_LINE}" "${PYTHON_USE_FILE}"; then
        info "Removing line '${PYTHON_USE_LINE}' from ${PYTHON_USE_FILE}..."
        # Use sed with sudo to delete the exact line in place
        run_sudo sed -i "\%^${PYTHON_USE_LINE}$%d" "${PYTHON_USE_FILE}" || warn "Failed to remove line from ${PYTHON_USE_FILE}."

        # Optional: Remove the file if it's now empty
        # Use sudo to check file size with stat, handle potential errors
        if [[ "$(run_sudo stat -c %s "${PYTHON_USE_FILE}" 2>/dev/null || echo 1)" == "0" ]]; then
             info "Removing empty USE flag file: ${PYTHON_USE_FILE}"
             run_sudo rm -f "${PYTHON_USE_FILE}" || warn "Failed to remove empty USE flag file ${PYTHON_USE_FILE}."
        fi

        warn "-----------------------------------------------------------------------"
        warn "Removed JAPIRC's USE flag configuration for dev-lang/python."
        warn "To fully revert the changes made by the installer, you may need to"
        warn "re-emerge Python to apply the potentially changed USE flags."
        warn "Run the following command and review the proposed changes carefully:"
        warn "  sudo emerge --ask --changed-use --deep dev-lang/python"
        warn "-----------------------------------------------------------------------"
    else
        info "Line '${PYTHON_USE_LINE}' not found in ${PYTHON_USE_FILE}. Skipping USE flag modification."
        # Optionally remove the file if it exists but doesn't contain the line (might be leftover/empty)
         if [[ "$(run_sudo stat -c %s "${PYTHON_USE_FILE}" 2>/dev/null || echo 1)" == "0" ]]; then
             info "Removing empty USE flag file: ${PYTHON_USE_FILE}"
             run_sudo rm -f "${PYTHON_USE_FILE}" || warn "Failed to remove empty USE flag file ${PYTHON_USE_FILE}."
         fi
    fi
elif command_exists emerge; then
     # Only mention this if emerge exists but the file wasn't found
     info "Gentoo USE flag configuration file ${PYTHON_USE_FILE} not found. Skipping USE flag removal."
fi


# --- Final Confirmation ---

info "-------------------------------------------"
info " ${APP_NAME} uninstallation process finished."
info " Removed items (if they existed):"
info "  - Executable: ${TARGET_BIN_DIR}/${MAIN_EXECUTABLE_NAME}"
info "  - Symlinks: ${TARGET_BIN_DIR}/${LINK_NAMES[*]}"
info "  - Virtual Env: ${VENV_DIR}"
info "  - Gentoo USE flag config (if applicable): ${PYTHON_USE_FILE}"
info ""
info " System packages installed via package managers (apt, dnf, pacman, emerge)"
info " like python3, python3-tk, etc., were NOT removed by this script."
info " You can remove them using your system's package manager if desired."
info "-------------------------------------------"

exit 0
