# NVDA Claude Desktop Accessibility Add-on

This NVDA add-on makes Claude Desktop more accessible for screen reader users.

## Features

- **Status Announcements**: Automatically speaks status updates from Claude Desktop (e.g., "thinking", "generating", "processing")
- **Response Focus**: When Claude finishes generating a response, the add-on announces "Response complete" and moves focus to the beginning of the response so you can read it with the screen reader

## Requirements

- NVDA 2023.1 or later
- Claude Desktop for Windows (Electron app)

## Installation

1. Download the `.nvda-addon` file from the releases page
2. Double-click the file to install, or use NVDA's Add-on Manager
3. Restart NVDA when prompted

## Usage

Once installed, the add-on works automatically when Claude Desktop is running:

1. Open Claude Desktop
2. Type your message and send it
3. The add-on will announce status changes as Claude processes your request
4. When the response is complete, NVDA will announce "Response complete" and focus the response

## Building from Source

Requires Python 3.10+ and SCons:

```powershell
# Install dependencies
pip install scons markdown

# Build the add-on
scons

# Create a development build with date-based version
scons dev=1
```

## License

This add-on is licensed under the GNU General Public License version 2 (GPL-2.0).

## Author

Stefan Lohmaier <stefan@slohmaier.de>

## Contributing

Contributions are welcome! Please submit issues and pull requests on GitHub.
