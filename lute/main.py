"""
User entry point.

Start lute running on given port, or 5001 if not set.

e.g.

python -m lute.main --port 5001
"""
import errno
import os
import argparse
import shutil
import logging
import textwrap
import gzip
from waitress import serve
from lute import __version__
from lute.app_factory import create_app, data_initialization
from lute.config.app_config import AppConfig
from lute.db import db

logging.getLogger("waitress.queue").setLevel(logging.ERROR)
logging.getLogger("natto").setLevel(logging.CRITICAL)


def _print(s):
    """
    Print message to stdout.
    """
    if isinstance(s, str):
        s = s.split("\n")
    msg = "\n".join(f"  {lin}" for lin in s)
    print(msg, flush=True)


def _create_prod_config_if_needed():
    """
    If config.yml is missing, create one from prod config.
    """
    config_file = os.path.join(AppConfig.configdir(), "config.yml")
    if not os.path.exists(config_file):
        prod_conf = os.path.join(AppConfig.configdir(), "config.yml.prod")
        shutil.copy(prod_conf, config_file)
        _print(["", "Using new production config.", ""])


def _get_config_file_path(config_file_path=None):
    """
    Get final config file to use.

    Uses config file if set (throws if doesn't exist);
    otherwise, uses the prod config, creating a prod config
    if necessary.
    """
    use_config = config_file_path
    if config_file_path is not None:
        _print(f"Using specified config: {config_file_path}")
    elif os.path.exists("config.yml"):
        _print("Using config.yml found in root")
        use_config = "config.yml"
    else:
        _print("Using default config")
        _create_prod_config_if_needed()
        use_config = AppConfig.default_config_filename()

    ac = AppConfig(use_config)
    _print(f"  data path: {ac.datapath}")
    _print(f"  database:  {ac.dbfilename}")
    if ac.is_docker:
        _print("  (Note these are container paths, not host paths.)")
    _print("")

    return use_config, ac


def _start(args):
    "Configure and start the app."
    _print(f"\nStarting Lute version {__version__}.\n")

    config_file_path, ac = _get_config_file_path(args.config)    
    app = create_app(config_file_path, output_func=_print)

    # 👇 COPY BACKUPS from repo to live backup dir
      # 👇 Copy .db.gz backups from lute3/backups to app's expected backup dir
    try:
        # Determine source and destination
        src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
        dst = os.path.join(ac.datapath, "backups")

        # Create destination if it doesn't exist
        os.makedirs(dst, exist_ok=True)

        # Copy .db.gz files
        if os.path.exists(src):
            for f in os.listdir(src):
                if f.endswith(".db.gz"):
                    shutil.copy(os.path.join(src, f), dst)
            _print("Copied .db.gz backup files to app backup directory.\n")
        else:
            _print(f"Backup source directory not found: {src}")
    except Exception as copy_err:
        _print(f"Warning: Failed to copy backups — {copy_err}")
    # 👆 COPY BACKUPS from repo to live backup dir
    # delete after copying

    with app.app_context():
        data_initialization(db.session, _print)

    close_msg = """
    When you're finished reading, stop this process
    with Ctrl-C or your system equivalent.
    """
    if app.env_config.is_docker:
        close_msg = """
        When you're finished reading, stop this container
        with Ctrl-C, docker compose stop, or docker stop <containerid>
        as appropriate.
        """
    _print(textwrap.dedent(close_msg))

    host_ip = "127.0.0.1" if args.local else "0.0.0.0"
    ip_port = f"{host_ip}:{args.port}"
    msg = f"""Lute v{__version__} is running on {ip_port}.  Open a web browser and go to:

    http://localhost:{args.port}
    """
    _print(textwrap.dedent(msg))

    try:
        serve(app, host=host_ip, port=args.port)
    except OSError as err:
        if err.errno == errno.EADDRINUSE:
            msg = [
                f"ERROR: port {args.port} is already in use.",
                "please try adding a --port parameter, e.g.:",
                "",
                "  python -m lute.main --port 9876",
                "",
            ]
            _print(msg)
        else:
            # Throw back up, to get general error message
            raise


def start():
    "Main entry point.  Called via scripts and pyproject.toml."
    parser = argparse.ArgumentParser(description="Start lute.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run local only (not accessible on other devices on the same network)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 5001)),
        help="Port number (default: 5001 or $PORT if set)"
    )

    parser.add_argument(
        "--config",
        help="Path to override config file.  Uses lute/config/config.yml if not set.",
    )
    parser.add_argument(
        "--restore-backup",
        help="Filename (in backups/) to restore, e.g., lute_backup_2023-10-04_022616.db.gz"
    )

    try:
        _start(parser.parse_args())
    except Exception as e:  # pylint: disable=broad-exception-caught
        dashes = "-" * 50
        failmsg = f"""
        {dashes}
        Error during startup:
        Type: {type(e)}
        {e}

        Please check your setup and try again.
        Ask for help on Discord, or report an issue on GitHub.
        Additionally, help is available with --help.
        {dashes}
        """

        print(textwrap.dedent(failmsg))


if __name__ == "__main__":
    start()
