"""Dateihelfer fuer Installer und Updater: Schreibschutz entfernen, robust kopieren und loeschen."""
import os
import shutil
import stat


def make_writable(path):
    if os.path.exists(path):
        os.chmod(path, stat.S_IWRITE)


def force_delete(function, path, _error):
    try:
        make_writable(path)
        function(path)
    except OSError:
        pass


def copy_file(source, target):
    make_writable(target)
    shutil.copy2(source, target)
    make_writable(target)


def remove_tree(folder):
    shutil.rmtree(folder, onexc=force_delete)
