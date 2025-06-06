"""
Backup routes.

Backup settings form management, and running backups.
"""

import os
import gzip
import shutil
import traceback
from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    jsonify,
    redirect,
    send_file,
    flash,
)
from lute.db import db
from lute.models.repositories import UserSettingRepository
from lute.backup.service import Service
from lute.models.book import Book
from sqlalchemy.orm import scoped_session, sessionmaker


bp = Blueprint("backup", __name__, url_prefix="/backup")


def _get_settings():
    "Get backup settings."
    repo = UserSettingRepository(db.session)
    return repo.get_backup_settings()


@bp.route("/index")
def index():
    """
    List all backups.
    """
    settings = _get_settings()
    service = Service(db.session)
    backups = service.list_backups(settings.backup_dir)
    backups.sort(reverse=True)

    return render_template(
        "backup/index.html", backup_dir=settings.backup_dir, backups=backups
    )


@bp.route("/download/<filename>")
def download_backup(filename):
    "Download the given backup file."
    settings = _get_settings()
    fullpath = os.path.join(settings.backup_dir, filename)
    return send_file(fullpath, as_attachment=True)


@bp.route("/backup", methods=["GET"])
def backup():
    """
    Endpoint called from front page.

    With extra arg 'type' for manual.
    """
    backuptype = "automatic"
    if "type" in request.args:
        backuptype = "manual"

    settings = _get_settings()
    return render_template(
        "backup/backup.html", backup_folder=settings.backup_dir, backuptype=backuptype
    )


@bp.route("/do_backup", methods=["POST"])
def do_backup():
    """
    Ajax endpoint called from backup.html.
    """
    backuptype = "automatic"
    prms = request.form.to_dict()
    if "type" in prms:
        backuptype = prms["type"]

    c = current_app.env_config
    settings = _get_settings()
    service = Service(db.session)
    is_manual = backuptype.lower() == "manual"
    try:
        f = service.create_backup(c, settings, is_manual=is_manual)
        flash(f"Backup created: {f}", "notice")
        return jsonify(f)
    except Exception as e:  # pylint: disable=broad-exception-caught
        tb = traceback.format_exc()
        return jsonify({"errmsg": str(e) + " -- " + tb}), 500


@bp.route("/skip_this_backup", methods=["GET"])
def handle_skip_this_backup():
    "Update last backup date so backup not attempted again."
    service = Service(db.session)
    service.skip_this_backup()
    return redirect("/", 302)

@bp.route("/restore/<filename>", methods=["POST"])
def restore_backup(filename):
    """
    Restore a backup by replacing the active lute.db with the selected backup.
    """
    settings = _get_settings()
    service = Service(db.session)

    try:
        backup_path = os.path.join(settings.backup_dir, filename)
        db_path = current_app.env_config.dbfilename
        backup_tmp_path = db_path + ".restoring"

        print(f"⏳ Starting restore...")
        print(f"📦 Backup file: {backup_path}")
        print(f"📍 Current db path: {db_path}")
        print(f"📂 Temp restore file: {backup_tmp_path}")

        # Unzip the .gz backup to a temp file
        with gzip.open(backup_path, 'rb') as f_in, open(backup_tmp_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
            print("✅ Unzipped backup to temp file.")

        # Rename current db as a backup
        original_backup = db_path + ".pre_restore"
        if os.path.exists(db_path):
            shutil.move(db_path, original_backup)
            print(f"📁 Moved existing lute.db to {original_backup}")

        # Move restored db into place
        shutil.move(backup_tmp_path, db_path)
        print("✅ Restored db moved into place.")

        # Step 4: Connect to restored DB and count books (quick validation)
        Session = scoped_session(sessionmaker(bind=db.engine))
        new_session = Session()
        book_count = new_session.query(Book).count()
        print(f"📚 Books in restored DB: {book_count}")
        new_session.close()

        # Trigger Render restart
        os.system("touch restart.txt")
        print("🔁 Triggered app restart.")

        flash(f"✅ Restored backup: {filename} — {book_count} books found.", "notice")
        flash(f"Restoring from backup: {backup_path}", "notice")
        flash(f"Restoring to: {db_path}", "notice")

        print(f"✅ Restore successful: {filename}")
    except Exception as e:
        traceback.print_exc()
        error_msg = f"❌ Failed to restore backup: {str(e)}"
        flash(error_msg, "error")
        print(error_msg)

    return redirect("/backup/index")

@bp.route("/debug_db")
def debug_db():
    from lute.models.book import Book
    count = db.session.query(Book).count()
    return f"📚 Book count in current DB: {count}"